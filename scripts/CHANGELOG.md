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
