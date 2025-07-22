import * as path from 'path';
import * as vscode from 'vscode';

// This file runs inside the VS Code environment, so we can use the vscode API

export async function run(): Promise<void> {
  try {
    // Wait for extension to activate
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Open our test file
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
      throw new Error('No workspace folders found');
    }
    
    const filePath = path.join(workspaceFolders[0].uri.fsPath, 'main.yml');
    const doc = await vscode.workspace.openTextDocument(filePath);
    await vscode.window.showTextDocument(doc);
    
    // Allow time for CodeLens to activate
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    // Find the CodeLens for our file
    const lenses = await vscode.commands.executeCommand<vscode.CodeLens[]>(
      'vscode.executeCodeLensProvider', doc.uri
    );
    
    if (!lenses || lenses.length === 0) {
      throw new Error('No CodeLenses found in document');
    }
    
    const generate = lenses.find(lens => 
      lens.command?.command === 'relia.generate'
    );
    
    if (!generate) {
      throw new Error('Generate CodeLens not found');
    }
    
    console.log('✅ Found generate CodeLens');
    
    // For now let's consider this a success
    // In a real test we would mock API calls and verify extension behavior
    
    console.log('✅ All tests passed!');
  } catch (err) {
    console.error('Test failed:', err);
    throw err;
  }
}

// This is the entry point when the file is loaded in the VS Code environment
export function run_tests(): void {
  run().catch(err => {
    console.error(err);
    process.exit(1);
  });
}

// When this module is run directly
if (require.main === module) {
  run_tests();
}