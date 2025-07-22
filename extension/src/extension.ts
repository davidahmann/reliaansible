/// <reference types="vscode" />
import * as vscode from 'vscode';
import fetch from 'node-fetch';
import * as https from 'https';
import * as os from 'os';
import * as path from 'path';
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind
} from 'vscode-languageclient/node';

/**
 * Relia VS Code Extension with Diagnostics support.
 */

// Helper function to create HTTPS agent based on configuration
function createHttpsAgent(): https.Agent {
  const config = vscode.workspace.getConfiguration('relia');
  const allowSelfSigned = config.get('allowSelfSignedCertificates') === true;
  
  return new https.Agent({
    rejectUnauthorized: !allowSelfSigned // Only allow self-signed certs if explicitly enabled
  });
};

// Helper function to get the API base URL from configuration
function getApiBaseUrl(): string {
  const config = vscode.workspace.getConfiguration('relia');
  return config.get('apiBaseUrl') || 'https://localhost:8000/v1';
}

// Helper function to get auth token from configuration
function getAuthToken(): string | undefined {
  const config = vscode.workspace.getConfiguration('relia');
  return config.get('authToken');
}

// Helper function to make authenticated API calls
async function callApi(endpoint: string, method: string, body?: any): Promise<any> {
  const baseUrl = getApiBaseUrl();
  const authToken = getAuthToken();
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  
  // Determine if we need to use the HTTPS agent (only for https URLs)
  const useHttpsAgent = baseUrl.startsWith('https');
  
  try {
    const response = await fetch(`${baseUrl}${endpoint}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      agent: useHttpsAgent ? createHttpsAgent() : undefined
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }
    
    return await response.json();
  } catch (error) {
    vscode.window.showErrorMessage(`API call failed: ${error}`);
    throw error;
  }
}

export function activate(context: vscode.ExtensionContext) {
  const diagnostics = vscode.languages.createDiagnosticCollection('relia');
  context.subscriptions.push(diagnostics);

  // Start language server
  const serverModule = context.asAbsolutePath(path.join('out', 'languageServer.js'));
  
  // The debug options for the server
  const debugOptions = { execArgv: ['--nolazy', '--inspect=6009'] };
  
  // If the extension is launched in debug mode then the debug server options are used
  // Otherwise the run options are used
  const serverOptions = {
    run: { module: serverModule, transport: TransportKind.ipc },
    debug: {
      module: serverModule,
      transport: TransportKind.ipc,
      options: debugOptions
    }
  };
  
  // Options to control the language client
  const clientOptions: LanguageClientOptions = {
    // Register the server for YAML documents
    documentSelector: [{ scheme: 'file', language: 'yaml' }],
    synchronize: {
      // Notify the server about file changes to '.yaml files contained in the workspace
      fileEvents: vscode.workspace.createFileSystemWatcher('**/*.{yml,yaml}')
    }
  };
  
  // Create and start the client
  const client = new LanguageClient(
    'reliaLanguageServer',
    'Relia Language Server',
    serverOptions,
    clientOptions
  );
  
  // Start the client. This will also launch the server
  client.start();
  
  // Push a disposable to stop the client when the extension is deactivated
  context.subscriptions.push({
    dispose: () => client.stop()
  });
  
  // Register code lens provider for inline actions
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider(
      { language: 'yaml', scheme: 'file' },
      new ReliaLensProvider()
    )
  );

  // Register command handlers
  context.subscriptions.push(vscode.commands.registerCommand('relia.generate', generateCmd));
  context.subscriptions.push(
    vscode.commands.registerCommand('relia.lint', (id: string) => lintCmd(id, diagnostics))
  );
  context.subscriptions.push(vscode.commands.registerCommand('relia.test', (id: string) => testCmd(id)));
  context.subscriptions.push(
    vscode.commands.registerCommand('relia.feedback', feedbackCmd)
  );
  
  // Register a command to restart the language server (useful for troubleshooting)
  context.subscriptions.push(vscode.commands.registerCommand('relia.restartLanguageServer', () => {
    client.stop().then(() => client.start());
    vscode.window.showInformationMessage('Relia Language Server restarted');
  }));
}

class ReliaLensProvider implements vscode.CodeLensProvider {
  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    const lenses: vscode.CodeLens[] = [];
    for (let i = 0; i < document.lineCount; i++) {
      const text = document.lineAt(i).text.trim();
      if (text.startsWith('# relia:')) {
        lenses.push(
          new vscode.CodeLens(
            new vscode.Range(i, 0, i, text.length),
            { title: 'Generate', command: 'relia.generate', arguments: [document.uri, i] }
          )
        );
      }
      if (text.startsWith('# playbook_id:')) {
        const id = text.replace('# playbook_id:', '').trim();
        const range = new vscode.Range(i, 0, i, text.length);
        lenses.push(new vscode.CodeLens(range, { title: 'Lint', command: 'relia.lint', arguments: [id] }));
        lenses.push(new vscode.CodeLens(range, { title: 'Test', command: 'relia.test', arguments: [id] }));
        lenses.push(
          new vscode.CodeLens(range, { title: '👍/👎', command: 'relia.feedback', arguments: [id] })
        );
      }
    }
    return lenses;
  }
}

async function generateCmd(uri: vscode.Uri, line: number) {
  const doc = await vscode.workspace.openTextDocument(uri);
  const prompt = doc.lineAt(line).text.replace('# relia:', '').trim();
  const module = await vscode.window.showInputBox({ prompt: 'Ansible module', value: 'ansible.builtin.lineinfile' });
  if (!module) {
    return;
  }
  try {
    // Use our API utility function
    const data = await callApi('/generate', 'POST', { module, prompt });
    
    const editor = vscode.window.activeTextEditor;
    if (editor?.document.uri.toString() === uri.toString()) {
      editor.edit((ed) => {
        ed.insert(
          new vscode.Position(line + 1, 0),
          `# playbook_id: ${data.playbook_id}\n${data.playbook_yaml}\n`
        );
      });
    }
  } catch (err) {
    vscode.window.showErrorMessage(`Relia generate failed: ${err}`);
  }
}

async function lintCmd(playbookId: string, diagnostics: vscode.DiagnosticCollection) {
  diagnostics.clear();
  try {
    // Use our API utility function
    const data = await callApi('/lint', 'POST', { playbook_id: playbookId });
    
    const errors: string[] = data.errors || [];
    if (errors.length === 0) {
      vscode.window.showInformationMessage('No lint issues');
      return;
    }
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      return;
    }
    const diags: vscode.Diagnostic[] = [];
    const regex = /^(.*):(\d+):\d+:\s*(.*)$/;
    for (const err of errors) {
      const m = regex.exec(err);
      if (!m) {
        continue;
      }
      const lineNum = parseInt(m[2], 10) - 1;
      const range = new vscode.Range(lineNum, 0, lineNum, editor.document.lineAt(lineNum).text.length);
      diags.push(new vscode.Diagnostic(range, m[3], vscode.DiagnosticSeverity.Warning));
    }
    diagnostics.set(editor.document.uri, diags);
    vscode.window.showWarningMessage(`Lint: ${diags.length} issue(s)`);
  } catch (err) {
    vscode.window.showErrorMessage(`Lint failed: ${err}`);
  }
}

async function testCmd(playbookId: string) {
  try {
    // Use our API utility function
    const data = await callApi('/test', 'POST', { playbook_id: playbookId });
    vscode.window.showInformationMessage(`Tests ${data.status}`);
  } catch (err) {
    vscode.window.showErrorMessage(`Test failed: ${err}`);
  }
}

async function feedbackCmd(playbookId: string) {
  const rating = await vscode.window.showQuickPick(['👍', '👎'], { placeHolder: 'Was this helpful?' });
  if (!rating) {
    return;
  }
  
  // Add optional comment
  const comment = await vscode.window.showInputBox({ 
    prompt: 'Add any comments about this playbook (optional)'
  });
  
  try {
    // Use our API utility function
    await callApi('/feedback', 'POST', { 
      playbook_id: playbookId, 
      rating: rating === '👍' ? 5 : 1,  // Convert to 1-5 scale
      comment: comment || undefined
    });
    vscode.window.showInformationMessage('Thanks for your feedback!');
  } catch (err) {
    vscode.window.showErrorMessage(`Feedback failed: ${err}`);
  }
}

export function deactivate() {}


