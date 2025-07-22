// This is the entry point for VS Code tests
const runTest = require('./out/tests/runTest');

// Export the run function that will be called by VS Code
module.exports = runTest.run_tests;