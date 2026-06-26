## 3.0.0 (2026-06-26)

### Feature 

- added support for WatsonX Light Weight Engine 
- added support for CP4BA OpenSearch integration
- added support for WatsonX validation using ibm_watsonx_ai package

### Chore

- update to python libraries

## 2.0.1 (2026-02-20)

### Fix

- fix for silent deployment regarding license acceptance

## 2.0.0 (2025-12-29)

### Fix

- update to python libraries
- OCP airgap load_images script environment variable fix for updated tool binaries: ibm-pak, oc-mirror

### Feature

- additional logging added for must_gather, upgrade and load_images scripts
- tls-verify flag added for load_images, deploy and upgrade script to skip tls verification for registry connections through podman 
- casepackage version is now auto-detected
- casepackage version flag has been added to override auto-detection
- context path support added for registry connections in load_images script
- enhanced catalog source and deployment rollout checks
- added support for pdb and hpa collection in mustgather

## 1.1.3 (2025-12-11)

### Fixes 

- updated python packages to latest versions
- fixed kubernetes API client logging 
- fixed cleanup task count UI display issue
- removed `ROKS` platform option -- only `OCP` or `CNCF` is supported

### Feat

- added support for operator upgrade
- added support for version 1.0.1
- added support for CP4BA license type 
- added support for auto-detecting version 
- added support for in-cluster kubernetes client connection
