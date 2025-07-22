import {
  createConnection,
  ProposedFeatures,
  TextDocuments,
  InitializeParams,
  TextDocumentSyncKind,
  Diagnostic,
  DiagnosticSeverity,
  DidChangeConfigurationNotification,
  CompletionItem,
  CompletionItemKind,
  TextDocumentPositionParams,
  Position,
  Range
} from 'vscode-languageserver/node';
import { TextDocument } from 'vscode-languageserver-textdocument';
import * as http from 'http';
import * as https from 'https';

// Create a connection for the server
const connection = createConnection(ProposedFeatures.all);

// Create a manager for opened text documents
const documents: TextDocuments<TextDocument> = new TextDocuments(TextDocument);

// Server configuration
interface ReliaServerConfiguration {
  apiBaseUrl: string;
  authToken: string;
  allowSelfSignedCertificates: boolean;
  maxNumberOfProblems: number;
}

// Default settings
const defaultSettings: ReliaServerConfiguration = {
  apiBaseUrl: 'https://localhost:8000/v1',
  authToken: '',
  allowSelfSignedCertificates: false,
  maxNumberOfProblems: 100
};

// Cache the settings of all open documents
let globalSettings: ReliaServerConfiguration = defaultSettings;
const documentSettings: Map<string, Thenable<ReliaServerConfiguration>> = new Map();

// Common Ansible keywords for completion
const ansibleKeywords = [
  'name', 'hosts', 'tasks', 'vars', 'become', 'become_user', 'gather_facts', 
  'handlers', 'pre_tasks', 'post_tasks', 'roles', 'tags', 'when', 'register', 'with_items',
  'loop', 'notify', 'ignore_errors', 'failed_when', 'changed_when', 'no_log', 'environment',
  'module_defaults', 'vars_files', 'vars_prompt', 'delegate_to'
];

// Common Ansible modules for completion
const ansibleModules = [
  'ansible.builtin.command', 'ansible.builtin.shell', 'ansible.builtin.template', 
  'ansible.builtin.copy', 'ansible.builtin.file', 'ansible.builtin.lineinfile',
  'ansible.builtin.service', 'ansible.builtin.apt', 'ansible.builtin.yum',
  'ansible.builtin.dnf', 'ansible.builtin.package', 'ansible.builtin.user',
  'ansible.builtin.group', 'ansible.builtin.systemd', 'ansible.builtin.git',
  'ansible.builtin.uri', 'ansible.builtin.get_url', 'ansible.builtin.cron'
];

// Helper function to create HTTPS agent based on configuration
function createHttpsAgent(allowSelfSigned: boolean): https.Agent {
  return new https.Agent({
    rejectUnauthorized: !allowSelfSigned // Only allow self-signed certs if explicitly enabled
  });
}

// Helper function to make API calls
async function callApi(endpoint: string, method: string, config: ReliaServerConfiguration, body?: any): Promise<any> {
  const baseUrl = config.apiBaseUrl;
  const authToken = config.authToken;
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };
  
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  
  // Determine if we need to use the HTTPS agent (only for https URLs)
  const useHttpsAgent = baseUrl.startsWith('https');
  
  return new Promise((resolve, reject) => {
    const url = new URL(`${baseUrl}${endpoint}`);
    const isHttps = url.protocol === 'https:';
    
    const options = {
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname + url.search,
      method: method,
      headers: headers,
      agent: useHttpsAgent ? createHttpsAgent(config.allowSelfSignedCertificates) : undefined
    };
    
    const req = (isHttps ? https : http).request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
      });
      
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(data));
          } catch (error) {
            resolve(data);
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        }
      });
    });
    
    req.on('error', (error) => {
      reject(error);
    });
    
    if (body) {
      req.write(JSON.stringify(body));
    }
    
    req.end();
  });
}

// Handle configuration change
connection.onDidChangeConfiguration(change => {
  if (change.settings.relia) {
    globalSettings = {
      ...defaultSettings,
      ...change.settings.relia
    };
  } else {
    globalSettings = defaultSettings;
  }

  // Reset all cached document settings
  documentSettings.clear();
  
  // Revalidate all open documents
  documents.all().forEach(validateYamlDocument);
});

function getDocumentSettings(resource: string): Thenable<ReliaServerConfiguration> {
  let result = documentSettings.get(resource);
  if (!result) {
    result = connection.workspace.getConfiguration({
      scopeUri: resource,
      section: 'relia'
    });
    documentSettings.set(resource, result);
  }
  return result;
}

// Remove document settings on close
documents.onDidClose(e => {
  documentSettings.delete(e.document.uri);
});

// Validate document on change
documents.onDidChangeContent(change => {
  validateYamlDocument(change.document);
});

// Lint the YAML document for Ansible playbook issues
async function validateYamlDocument(textDocument: TextDocument): Promise<void> {
  const settings = await getDocumentSettings(textDocument.uri);
  const text = textDocument.getText();
  const pattern = /^---/;
  
  // Skip validation for non-playbook files
  if (!pattern.test(text)) {
    return;
  }

  const diagnostics: Diagnostic[] = [];
  
  // Basic YAML validation
  validateBasicYaml(text, diagnostics);
  
  // Playbook ID detection and validation
  const playbookId = extractPlaybookId(text);
  if (playbookId) {
    try {
      // Try to validate via API if we have auth token
      if (settings.authToken) {
        const data = await callApi('/validate', 'POST', settings, { playbook_id: playbookId });
        
        if (data.errors && Array.isArray(data.errors)) {
          // Add API validation errors to diagnostics
          for (const error of data.errors) {
            // Parse line information from error message
            const match = /line (\d+).*: (.+)/.exec(error);
            if (match) {
              const line = parseInt(match[1], 10) - 1;
              const lineText = textDocument.getText(Range.create(line, 0, line, 100));
              
              diagnostics.push({
                severity: DiagnosticSeverity.Warning,
                range: {
                  start: { line, character: 0 },
                  end: { line, character: lineText.length }
                },
                message: match[2],
                source: 'relia'
              });
            }
          }
        }
      }
    } catch (error) {
      // API validation failed, continue with basic validation
      connection.console.log(`API validation failed: ${error}`);
    }
  }
  
  // Send the diagnostics to the client
  connection.sendDiagnostics({ uri: textDocument.uri, diagnostics });
}

// Extract playbook ID from document
function extractPlaybookId(text: string): string | null {
  const match = /# playbook_id: ([a-zA-Z0-9-_]+)/.exec(text);
  return match ? match[1] : null;
}

// Validate basic YAML formatting
function validateBasicYaml(text: string, diagnostics: Diagnostic[]): void {
  const lines = text.split('\n');
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    // Check for common YAML errors
    if (line.includes('\t')) {
      diagnostics.push({
        severity: DiagnosticSeverity.Warning,
        range: {
          start: { line: i, character: line.indexOf('\t') },
          end: { line: i, character: line.indexOf('\t') + 1 }
        },
        message: 'Tab character found. Use spaces for indentation in YAML.',
        source: 'relia'
      });
    }
    
    if (line.trim().match(/:\s+$/)) {
      diagnostics.push({
        severity: DiagnosticSeverity.Information,
        range: {
          start: { line: i, character: 0 },
          end: { line: i, character: line.length }
        },
        message: 'Key with empty value.',
        source: 'relia'
      });
    }
    
    // Check for indentation issues
    const indentMatch = line.match(/^(\s*)/);
    if (indentMatch && indentMatch[1].length % 2 !== 0 && line.trim().length > 0) {
      diagnostics.push({
        severity: DiagnosticSeverity.Information,
        range: {
          start: { line: i, character: 0 },
          end: { line: i, character: indentMatch[1].length }
        },
        message: 'Indentation should be a multiple of 2 spaces.',
        source: 'relia'
      });
    }
  }
}

// Add auto-completion for common Ansible keywords and modules
connection.onCompletion(
  (_textDocumentPosition: TextDocumentPositionParams): CompletionItem[] => {
    const document = documents.get(_textDocumentPosition.textDocument.uri);
    if (!document) {
      return [];
    }
    
    const line = document.getText({
      start: { line: _textDocumentPosition.position.line, character: 0 },
      end: { line: _textDocumentPosition.position.line, character: _textDocumentPosition.position.character }
    });
    
    // Determine context for proper completion items
    const completionItems: CompletionItem[] = [];

    // For module name completion
    if (line.trim().match(/^\s*-\s*$/)) {
      ansibleModules.forEach(module => {
        completionItems.push({
          label: module,
          kind: CompletionItemKind.Module,
          detail: `Ansible module: ${module}`,
          insertText: `${module}:\n    `
        });
      });
    }
    
    // For key completion
    ansibleKeywords.forEach(keyword => {
      completionItems.push({
        label: keyword,
        kind: CompletionItemKind.Keyword,
        detail: `Ansible keyword: ${keyword}`,
        insertText: `${keyword}: `
      });
    });
    
    return completionItems;
  }
);

// Initialize the language server with capabilities
connection.onInitialize((params: InitializeParams) => {
  const capabilities = params.capabilities;

  return {
    capabilities: {
      textDocumentSync: TextDocumentSyncKind.Incremental,
      completionProvider: {
        resolveProvider: false,
        triggerCharacters: [' ', ':']
      }
    }
  };
});

// After initialization, request client configuration
connection.onInitialized(() => {
  connection.client.register(
    DidChangeConfigurationNotification.type,
    undefined
  );
});

// Listen for document events
documents.listen(connection);

// Listen on the connection
connection.listen();
