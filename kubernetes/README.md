# Kubernetes Deployment for Relia OSS

This directory contains Kubernetes manifests for deploying Relia OSS in a production environment.

## Components

* `deployment.yaml` - Main deployment for the backend service
* `service.yaml` - Service and Ingress resources for network access
* `hpa.yaml` - Horizontal Pod Autoscaler for dynamic scaling
* `networkpolicy.yaml` - Network policies for security
* `kustomization.yaml` - Kustomize configuration for managing deployments

## Setup

Before deploying, you'll need to:

1. Set up a Kubernetes cluster
2. Install and configure `kubectl`
3. Install [Kustomize](https://kustomize.io/) for deployment management
4. Create a container registry and push the container image
5. Set up [cert-manager](https://cert-manager.io/) for TLS certificates
6. Set up an Ingress controller (e.g., Nginx Ingress)

## Creating Secrets

You must create a `relia-secrets` Secret with the following keys:

```bash
kubectl create secret generic relia-secrets \
  --from-literal=jwt-secret=$(openssl rand -base64 32) \
  --from-literal=csrf-secret=$(openssl rand -base64 32)
```

## Deployment Steps

1. Update the placeholders in the manifests:
   - `${CONTAINER_REGISTRY}` - Your container registry URL
   - `${VERSION}` - The version tag for your image
   - `${DOMAIN}` - Your domain name

2. Deploy using Kustomize:
   ```bash
   kubectl apply -k .
   ```

3. Verify the deployment:
   ```bash
   kubectl get pods -l app=relia
   kubectl get services -l app=relia
   kubectl get ingress
   ```

## Security Features

These manifests include several security best practices:

- Non-root user in container
- Resource limits and requests
- Network policies to restrict traffic
- Read-only root filesystem
- Security contexts with least privilege
- TLS encryption for all traffic
- Content Security Policy and other security headers
- Horizontal Pod Autoscaler for reliability

## Customization

Modify the `kustomization.yaml` file to add environment-specific configurations or additional resources.