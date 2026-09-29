# IBM Content Assistant 1.0.4

[![Release](https://img.shields.io/badge/Release-1.0.4-blue.svg)](https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software/releases/tag/v1.0.4)
[![Helm](https://img.shields.io/badge/Helm-v3.10+-blue.svg)](https://helm.sh)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.24+-blue.svg)](https://kubernetes.io)
[![OpenShift](https://img.shields.io/badge/OpenShift-v4.10+-red.svg)](https://www.openshift.com)
[![Python](https://img.shields.io/badge/Python-3.12+-yellow.svg)](https://www.python.org)

## 📋 Table of Contents

- [Overview](#overview)
- [Release Information](#release-information)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Python DevOps Scripts](#python-devops-scripts)
- [Documentation](#documentation)
- [Support](#support)

## 🎯 Overview

This repository provides comprehensive resources for deploying and managing **IBM Content Assistant (CAS)** on Kubernetes and OpenShift platforms. It includes:

- **Python DevOps Scripts**: Interactive and silent CLI tools for deployment automation, vector database validation, and lifecycle management
- **Deployment Descriptors**: Kubernetes manifests for the Content Assistant operator, `CASCluster` Custom Resource, OpenSearch vector database, and Usage Metering
- **Helm Charts**: Packaged Helm chart (`ibm-content-assistant-operator`) and direct repository access
- **Documentation**: Comprehensive guides, configuration references, and troubleshooting resources

### What is IBM Content Assistant?

IBM Content Assistant (CAS) is an AI-powered content assistant platform integrated with IBM Content Cortex and IBM Cloud Pak for Business Automation. It centralizes and activates content intelligence by providing:

- **CASCluster Operator**: Manages the full lifecycle of the Content Assistant deployment via the `CASCluster` (`cas.ibm.com/v1`) custom resource
- **GenAI Connector (`genaiconnector`)**: Core microservice providing generative AI inference, LLM provider integration, and prompt orchestration
- **Model Gateway Support**: Seamless proxy routing for LLM providers and embedding models
- **Vector Database Integration**: Native support for OpenSearch clusters with Basic Auth and OIDC authentication for semantic retrieval and embeddings
- **Usage Metering**: Integrated usage and metrics collection via the IBM Usage Metering operator
- **Flexible Deployment Models**: Works with IBM Content Cortex (`fncm`) and IBM Cloud Pak for Business Automation (`cp4ba`) environments

## 📊 Release Information

| Release | Version | Helm Chart Version | App Version | Date |
|:---:|:---:|:---:|:---:|:---:|
| IBM Content Assistant 1.0.4 | 1.0.4 | 1.4.0 | 1.0.0 | 2026-09-30 |

> **Note**: For detailed component versions, image digests, and release highlights, see [`release-note.md`](release-note.md) or the [Releases](https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software/releases) page.

### Resources

- **Product Website**: [IBM Content Assistant Website](https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/)
- **Documentation**: [IBM Content Assistant Documentation](https://www.ibm.com/docs/en/cacms/1.0.x)
- **Helm Repository**: [https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/charts](https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/charts)
- **License Information**: [IBM Content Assistant License (1.0.0)](https://ibm.biz/CAS_License_1_0_0) | [Software Notices](https://ibm.biz/CAS_Notices_1_0_0)

## 📁 Repository Structure

```
cert-kubernetes-content-assistant/
├── README.md                          # This file
├── release-note.md                    # Release notes and image reference details
├── version.toml                       # Component versions and release metadata
├── descriptors/                       # Kubernetes and OpenShift deployment descriptors
│   ├── content-assistant/             # Content Assistant operator, CRD, RBAC, and OLM manifests
│   │   ├── cas_v1_cas_crd.yaml        # CASCluster CustomResourceDefinition (cas.ibm.com/v1)
│   │   ├── ibm_content_assistant_cr.yaml       # Minimal CASCluster Custom Resource
│   │   ├── ibm_content_assistant_full_cr.yaml  # Fully annotated CASCluster Custom Resource
│   │   ├── operator.yaml              # Operator Deployment manifest
│   │   ├── op-olm/                    # OLM resources (CatalogSource, OperatorGroup, Subscription)
│   │   └── rbac/                      # ServiceAccount, Role, and RoleBinding manifests
│   ├── opensearch/                    # OpenSearch vector database descriptors and secrets
│   └── usage-metering/                # Usage Metering operator, CRD, and CR descriptors
│       ├── ica-metrics/               # Metric definition descriptors
│       ├── op-olm/                    # OLM resources
│       └── rbac/                      # RBAC manifests
├── helm-charts/                       # Helm charts
│   ├── content-assistant/             # Helm chart for IBM Content Assistant operator (v1.4.0)
│   └── ibm-usage-metering/            # Helm chart for IBM Usage Metering operator (v1.0.7)
└── scripts/                           # Python DevOps automation suite
    ├── README.rst                     # DevOps scripts guide and CLI reference
    ├── requirements.txt               # Python package dependencies
    ├── prerequisites.py               # Input gathering, artifact generation, and validation
    ├── deploy_operator.py             # Operator deployment automation (Helm and OLM)
    ├── upgrade_deployment.py          # Upgrade workflow automation
    ├── clean_deployment.py            # Deployment and operator removal automation
    ├── load_images.py                 # Private registry and air-gap image loading
    ├── must_gather.py                 # Diagnostic log and resource collector
    ├── silent_config/                 # Silent mode configuration files (.toml)
    └── helper_scripts/                # Modular library modules (gather, deploy, validate, etc.)
```

## 🚀 Quick Start

### Prerequisites

Before deploying IBM Content Assistant, ensure you have:

- **Kubernetes / OpenShift Cluster**: Kubernetes v1.24+ or OpenShift Container Platform v4.10+
- **Helm**: v3.10+ (for Helm installations)
- **kubectl / oc**: Configured with cluster administrator access
- **Python**: 3.12+ (for Python DevOps automation suite)
- **Vector Database**: OpenSearch 3.5.0+ reachable with valid credentials/certificates
- **IBM Entitlement Key**: From [IBM Container Library](https://myibm.ibm.com/products-services/containerlibrary)

---

### Method 1: Python DevOps Scripts (Recommended)

The interactive Python DevOps scripts automate environment validation, operator deployment, and CR generation:

```bash
# 1. Navigate to the scripts directory
cd scripts/

# 2. Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install script dependencies
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# 4. (Air-gap only) Generate manifest and mirror images
python3 load_images.py generate
python3 load_images.py push

# 5. Deploy operators (interactive guided mode)
python3 deploy_operator.py

# 6. Gather prerequisites and generate CR configuration
python3 prerequisites.py gather
python3 prerequisites.py generate
python3 prerequisites.py validate
```

---

### Method 2: Helm Installation

Install the IBM Content Assistant Operator directly using Helm:

```bash
# 1. Add the Content Assistant Helm repository
helm repo add ibm-content-assistant https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/charts
helm repo update

# 2. Create the target namespace
kubectl create namespace cas

# 3. Create the IBM Entitlement Key pull secret
kubectl create secret docker-registry ibm-entitlement-key \
  --docker-server=cp.icr.io \
  --docker-username=cp \
  --docker-password=<your-entitlement-key> \
  --namespace cas

# 4. Install the Content Assistant operator chart
helm install ibm-content-assistant-operator ibm-content-assistant/ibm-content-assistant-operator \
  --namespace cas

# 5. (Optional) Install Usage Metering operator chart
helm install ibm-usage-metering ibm-content-assistant/ibm-usage-metering \
  --namespace cas

# 6. Apply your CASCluster Custom Resource
kubectl apply -f descriptors/content-assistant/ibm_content_assistant_cr.yaml -n cas
```

---

### Method 3: Direct Descriptors (kubectl / oc)

```bash
# 1. Apply the CASCluster CRD
kubectl apply -f descriptors/content-assistant/cas_v1_cas_crd.yaml

# 2. Apply operator RBAC
kubectl apply -f descriptors/content-assistant/rbac/service_account.yaml -n <namespace>
kubectl apply -f descriptors/content-assistant/rbac/role.yaml -n <namespace>
kubectl apply -f descriptors/content-assistant/rbac/role_binding.yaml -n <namespace>

# 3. Deploy the operator
kubectl apply -f descriptors/content-assistant/operator.yaml -n <namespace>

# 4. Deploy and configure CASCluster CR (fill all <Required> fields first)
kubectl apply -f descriptors/content-assistant/ibm_content_assistant_cr.yaml -n <namespace>
```

---

## 🐍 Python DevOps Scripts

The [`scripts/`](scripts/) directory contains a suite of CLI tools for IBM Content Assistant lifecycle management:

### Available Scripts

| Script | Purpose | Key Features |
|---|---|---|
| [`prerequisites.py`](scripts/prerequisites.py) | Deployment preparation | Gathers vector DB credentials, validates cluster and endpoints, generates YAML artifacts |
| [`deploy_operator.py`](scripts/deploy_operator.py) | Operator deployment | Deploys Content Assistant and Usage Metering operators via Helm or OLM |
| [`upgrade_deployment.py`](scripts/upgrade_deployment.py) | Upgrade automation | Guided CR and operator upgrade with dry-run support |
| [`clean_deployment.py`](scripts/clean_deployment.py) | Cleanup automation | Safely removes operator deployments, CR instances, and RBAC |
| [`load_images.py`](scripts/load_images.py) | Air-gap image loading | Generates image manifests and mirrors images to private registries |
| [`must_gather.py`](scripts/must_gather.py) | Diagnostics | Collects operator logs, CR status, pod diagnostics, and cluster resources |

### Key CLI Features

- 🎨 **Rich Terminal UI**: Formatted console output, styled tables, progress indicators, and interactive panels
- 🤖 **Guided Prompts**: Interactive configuration prompts with built-in validation
- 🔇 **Silent Mode**: Full automated execution using TOML property files in [`scripts/silent_config/`](scripts/silent_config/)
- 📝 **Comprehensive Logging**: Detailed log files generated for all deployment and upgrade operations
- 🧪 **Dry-Run Mode**: Preview deployment and upgrade actions before applying to the cluster

**Full Scripts Documentation**: [`scripts/README.rst`](scripts/README.rst)

---

## 📚 Documentation

- **Product Documentation**: [IBM Content Assistant Documentation (1.0.x)](https://www.ibm.com/docs/en/cacms/1.0.x)
- **Official Website & Guides**: [IBM Content Assistant Website](https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/)
- **Helm Chart Reference**: [`helm-charts/content-assistant/README.md`](helm-charts/content-assistant/README.md)
- **Release Details**: [`release-note.md`](release-note.md)
- **DevOps Suite Guide**: [`scripts/README.rst`](scripts/README.rst)

---

## 🔧 Support

### Getting Help

- **IBM Documentation**: [https://www.ibm.com/docs/en/cacms/1.0.x](https://www.ibm.com/docs/en/cacms/1.0.x)
- **IBM Support Portal**: [https://www.ibm.com/mysupport](https://www.ibm.com/mysupport)
- **GitHub Repository**: [ibm-ecm/ibm-content-assistant-client-managed-software](https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software)
- **Email**: ecm-container-service@ibm.com

### Collecting Diagnostics for Support

When opening a support case, use [`must_gather.py`](scripts/must_gather.py) to collect diagnostic data:

```bash
cd scripts/
python3 must_gather.py --verbose
```

---

## 📄 License

Licensed Materials - Property of IBM

© Copyright IBM Corp. 2026. All Rights Reserved.

US Government Users Restricted Rights - Use, duplication or disclosure restricted by GSA ADP Schedule Contract with IBM Corp.

---

**Repository**: [ibm-ecm/ibm-content-assistant-client-managed-software](https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software)  
**Version**: 1.0.4  
**Last Updated**: 2026-09-30
