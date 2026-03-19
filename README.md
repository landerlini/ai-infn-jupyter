# JupyterHub Helm Chart for AI-INFN

A production-ready Helm chart for deploying **JupyterHub** on Kubernetes with integrated support for GPU computing, batch job processing via Virtual Kubelet Dispatcher (VKD), and INFN Cloud IAM authentication.

## Overview

This project provides a complete GitOps configuration for deploying JupyterHub in a Kubernetes cluster. It's designed for research and data science workloads, particularly those requiring GPU access and integration with INFN Cloud infrastructure.

### Key Features

- **JupyterHub Integration**: Deploy and manage JupyterHub v4.3.2 on Kubernetes
- **OAuth Authentication**: INFN Cloud IAM integration with group-based access control
- **GPU Support**: GPU model detection and resource allocation
- **Batch Processing**: Virtual Kubelet Dispatcher (VKD) integration for batch job execution
- **Shared Storage**: NFS-based persistent storage for user data
- **CVMFS Support**: Read-only CVMFS volumes for scientific software
- **Custom Configuration**: Support for custom JupyterHub configurations and spawn forms
- **Metrics & Monitoring**: Built-in Prometheus metrics and health checks
- **Privileged User Support**: Special volumes and capabilities for authorized users

## Prerequisites

### Kubernetes Cluster
- Kubernetes 1.20+
- Helm 3.0+
- Ingress controller (e.g., nginx-ingress)
- StorageClass for SQLite database

### Infrastructure Requirements
- **NFS Server**: For shared storage with accessible management APIs (HTTP port)
  - Must have a folder named after the Helm release name
  - Requires credentials for admin user
- **OAuth Provider**: INFN Cloud IAM service (or compatible OAuth 2.0 provider)
- **Storage**: 
  - CVMFS StorageClass (optional but recommended)
  - SQLite PVC storage (1Gi minimum)

### Network Configuration
- TLS-terminated hostname (FQDN) accessible from the cluster
- Proper DNS resolution for the hostname
- Network access to NFS server and OAuth endpoint

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/landerlini/ai-infn-jupyter.git
cd ai-infn-jupyter
```

### 2. Configure Values

Edit `values.yaml` with your deployment-specific settings:

```bash
cp values.yaml values-production.yaml
# Edit values-production.yaml with your settings
```

**Critical settings to configure:**

- **`hostname`**: Your JupyterHub FQDN (e.g., `jupyter.example.infn.it`)
- **`nfsServerAddress`**: IP address of your NFS server
- **`nfsServerAdminUser` & `nfsServerAdminPassword`**: NFS server credentials
- **`IamClientId` & `IamClientSecret`**: OAuth client credentials from INFN Cloud IAM
- **`jhubProxySecretToken` & `jhubCookieSecret`**: Generate with:
  ```bash
  openssl rand -hex 32
  ```
- **`jhubCryptKey`**: Generate with:
  ```bash
  openssl rand -hex 32
  ```
- **`jhubOAuthGroups`**: IAM group(s) allowed to access JupyterHub
- **`jhubAdminGroups`**: IAM group(s) with administrator privileges

### 3. Deploy with Helm

```bash
helm install my-jhub . -f values-production.yaml -n jupyter --create-namespace
```

Or with ArgoCD for GitOps:

```bash
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jhub-ai-infn
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/landerlini/ai-infn-jupyter
    targetRevision: HEAD
    path: .
    helm:
      valueFiles:
      - values-production.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: jupyter
EOF
```

### 4. Verify Deployment

```bash
# Check pod status
kubectl get pods -n jupyter

# Check ingress
kubectl get ingress -n jupyter

# Access logs
kubectl logs -n jupyter deployment/my-jhub-hub
```

## Configuration Guide

### values.yaml Structure

- **Networking**: Hostname and ingress configuration
- **NFS Storage**: Server address, credentials, mount points
- **OAuth**: IAM provider details and group mappings
- **JupyterHub Core**: Image versions, API keys, timeouts
- **Virtual Kubelet**: Batch processing via VKD
- **User Environment**: CVMFS, privileged volumes, default images

### Optional Features

- **Custom JupyterHub Configuration** (`overrideJupyterHubConfig: true`)
  - Place `customconfig.py` in `resources/`
  - Place `spawn_form.jinja2.html` in `resources/`

- **GPU Support**
  - Configured through `resources/gpu-models.yaml`
  - Models automatically detected and presented to users

- **Virtual Kubelet Dispatcher** (`vkdEnabled: true`)
  - Enables batch job submission
  - Requires VKD namespace and service accounts

## Important Notes

### Security ⚠️

- **Never commit secrets** to version control. All credential fields (`IamClientSecret`, passwords, tokens) should be:
  - Kept empty in the repository
  - Provided via secure configuration management (ArgoCD Sealed Secrets, HashiCorp Vault, etc.)
  
- **Admin Groups**: Members of `jhubAdminGroups` have access to all users' data. Implement proper governance and ensure users have received appropriate authorization.

### NFS Requirements
This deployment relies on a NFS server with HTTP management interface developed in a separate repository: [ai-infn-nfs](https://github.com/landerlini/ai-infn-nfs).
The configuration of the server should include the jupyterHub user (UID 188 by default). For example,

```yaml
adminUser: <SAME USER AS DEFINED IN Values.nfsServerAdminPassword>
adminPassword: <SAME PASSWORD AS DEFINED IN Values.nfsServerAdminPassword>
serviceIP: <SAME IP AS DEFINED IN Values.nfsServerAddress>

clusterServices:
  jupyter: <SAME UID AS DEFINED IN Values.nfsUser>
  ... other accounts

anonDirs:
  www: 1777
  envs: 1777
  public: 1777
  vkd: 0777
  ... other public areas
```


### Performance & Capacity

- **SQLite Database**: Default 1Gi storage; adjust based on user count and session duration
- **Pod Startup**: `jhubStartTimeout` (120s default) may need adjustment for slow GPU initialization
- **Resource Quotas**: Configure based on your cluster capacity and user needs

## Monitoring & Observability

- **Prometheus Metrics**: Exposed at `/metrics` endpoint
- **ServiceMonitor**: Included for automatic Prometheus scraping
- **Metrics API Key**: Configured via `jhubMetricApiKey` for authentication
