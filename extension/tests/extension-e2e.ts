import * as path from 'path';
import * as fs from 'fs';
import { runTests, downloadAndUnzipVSCode } from '@vscode/test-electron';

// This is a test launcher file that runs outside VS Code
// The actual test logic will run inside VS Code environment
async function main() {
  try {
    // Create test workspace and sample file
    const workspace = path.join(__dirname, 'workspace');
    fs.mkdirSync(workspace, { recursive: true });
    const filePath = path.join(workspace, 'main.yml');
    fs.writeFileSync(filePath, '# relia: ensure ntp installed\n');

    // Path to extension root
    const extensionDevelopmentPath = path.resolve(__dirname, '..');
    
    // Path where test will actually run (inside VS Code)
    // This needs to be a separate file that will be loaded in the VS Code environment
    const extensionTestsPath = path.resolve(__dirname, './runTest');

    // Download and launch VS Code with our extension
    const vscodeExecutablePath = await downloadAndUnzipVSCode('stable');
    
    // Run the integration test
    await runTests({
      vscodeExecutablePath,
      extensionDevelopmentPath,
      extensionTestsPath,
      launchArgs: [workspace, '--disable-extensions']
    });
    
    console.log('Extension tests completed successfully');
  } catch (err) {
    console.error('Failed to run tests:', err);
    process.exit(1);
  }
}

// Start the tests
main();