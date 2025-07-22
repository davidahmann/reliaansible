# Relia VS Code Extension

[![Version](https://img.shields.io/visual-studio-marketplace/v/Relia.relia-oss?color=brightgreen)](https://marketplace.visualstudio.com/items?itemName=Relia.relia-oss)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/Relia.relia-oss?color=brightgreen)](https://marketplace.visualstudio.com/items?itemName=Relia.relia-oss)
[![Downloads](https://img.shields.io/visual-studio-marketplace/d/Relia.relia-oss?color=brightgreen)](https://marketplace.visualstudio.com/items?itemName=Relia.relia-oss)
[![Rating](https://img.shields.io/visual-studio-marketplace/r/Relia.relia-oss?color=brightgreen)](https://marketplace.visualstudio.com/items?itemName=Relia.relia-oss&ssr=false#review-details)
[![License](https://img.shields.io/github/license/relia-org/relia-oss?color=brightgreen)](https://github.com/relia-org/relia-oss/blob/main/LICENSE.md)

This extension adds support for generating and testing Ansible playbooks using the Relia AI assistant.

## Features

- Generate Ansible playbooks from natural language descriptions
- Lint your playbooks directly from VS Code
- Run tests on your playbooks
- Provide feedback on playbook quality
- Real-time YAML syntax validation with Ansible-specific checks
- Auto-completion for common Ansible keywords and modules
- Detailed diagnostics for YAML syntax errors

## Requirements

- VS Code version 1.60.0 or higher
- A running Relia backend service

## Extension Settings

This extension contributes the following settings:

* `relia.apiBaseUrl`: Base URL of the Relia API (use https:// for secure connections)
* `relia.authToken`: Authentication token for the Relia API
* `relia.allowSelfSignedCertificates`: Allow self-signed certificates (only enable for development environments)

## How to Use

1. Open a YAML file
2. Add a comment like `# relia: ensure nginx is installed and running`
3. Click on the "Generate" CodeLens that appears above the comment
4. Enter the Ansible module when prompted
5. The extension will generate a playbook below your comment

## Feedback and Issues

Please submit feedback and issues through our [GitHub repository](https://github.com/relia-org/relia-oss).

## License

This extension is released under the MIT License. See the [LICENSE](LICENSE.md) file for details.