###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2024. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

import os
from pathlib import Path

from rich import print
from rich.panel import Panel
from rich.text import Text

from ..utilities.prerequisites_utilites import write_yaml_to_file, write_log_to_file


# Create a MustGather Class

class MustGather:

    def __init__(self, console, namespace, logger=None, mustgather_folder="", deployment_details=dict, operator_details={}, kube=None):
        self._logger = logger
        self._console = console
        self._deployment_details = deployment_details
        self._operator_details = operator_details
        self._kube = kube
        self._mustgather_folder = mustgather_folder
        self._namespace = namespace
        self._version = "5.7.0"
        self._cr_name = ""
        if "name" in self._deployment_details.keys():
            self._cr_name = deployment_details["name"]
        if "version" in deployment_details.keys():
            self._version = deployment_details["version"]
        elif "release" in operator_details.keys():
            self._version = operator_details["release"]

    def to_dict(self):
        return {
            "deployment_details": self._deployment_details,
            "operator_details": self._operator_details,
            "mustgather_folder": self._mustgather_folder,
            "namespace": self._namespace,
            "cr_name": self._cr_name
        }

    def collect_cluster_info(self, progress):
        # Number of tasks = 4

        # Create folder for secrets if it does not exist
        cluster_folder_path = os.path.join(self._mustgather_folder, "cluster")
        if not os.path.exists(cluster_folder_path):
            os.makedirs(cluster_folder_path)
        try:

            self._logger.info("Collecting cluster version information")
            path = os.path.join(
                f"{cluster_folder_path}",
                "cluster_version.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                version_response = self._kube.get_version()
                write_yaml_to_file(version_response, path)
        except Exception as e:
            self._logger.info("Unable to retrieve version information, caught %s Skipping...", e)

        try:
            self._logger.info("Collecting cluster events")
            path = os.path.join(
                f"{cluster_folder_path}",
                "events.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                version_response = self._kube.get_events(self._namespace)
                write_yaml_to_file(version_response, path)


        except Exception as e:
            self._logger.info("Unable to retrieve events, caught %s Skipping...", e)

        try:
            self._logger.info("Collecting cluster node information")
            path = os.path.join(
                f"{cluster_folder_path}",
                "nodes.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                nodes = self._kube.get_nodes()
                write_yaml_to_file(nodes, path)

        except Exception as e:
            self._logger.info("Unable to retrieve nodes, caught %s Skipping...", e)

        try:
            self._logger.info("Collecting node resource allocations and usage")
            path = os.path.join(
                f"{cluster_folder_path}",
                "nodeusage.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                node = self._kube.get_node_top()
                write_yaml_to_file(node, path)

        except Exception as e:
            self._logger.info("Unable to retrieve node usage information, caught %s Skipping...", e)


    # Function to collect secrets information
    def collect_secret_info(self, progress, secrets=[]):

        # Create folder for secrets if it does not exist
        secrets_folder_path = os.path.join(self._mustgather_folder, "secrets")
        if not os.path.exists(secrets_folder_path):
            os.makedirs(secrets_folder_path)

        self._logger.info("Starting secrets information collection")

        for secret in secrets:
            try:
                self._logger.info(f"Collecting secret: {secret} details")
                path = os.path.join(
                    f"{secrets_folder_path}",
                    f"{secret}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    secret_response = self._kube.describe_secret(secret, self._namespace, progress)
                    write_yaml_to_file(secret_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve secret %s, caught %s Skipping...", secret, e)

        self._logger.info("Secrets information collection completed")

    # Function to collect configmap information
    def collect_configmap_info(self, progress, configmaps=[]):

        # Create folder for configmaps if it does not exist
        configmap_folder_path = os.path.join(self._mustgather_folder, "configmaps")
        if not os.path.exists(configmap_folder_path):
            os.makedirs(configmap_folder_path)

        self._logger.info("Starting ConfigMap information collection")

        for configmap in configmaps:
            try:
                self._logger.info(f"Collecting configmap: {configmap} info")
                path = os.path.join(
                    f"{configmap_folder_path}",
                    f"{configmap}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    configmap_response = self._kube.describe_configmap(configmap, self._namespace)
                    write_yaml_to_file(configmap_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve configmap %s, caught %s Skipping...", configmap, e)

        self._logger.info("ConfigMap information collection completed")

    # Function to collection deployment information
    def collect_deployment_info(self, progress, deployments=list):

        # Create folder for deployments if it does not exist
        deployment_folder_path = os.path.join(self._mustgather_folder, "deployments")
        if not os.path.exists(deployment_folder_path):
            os.makedirs(deployment_folder_path)

        self._logger.info("Starting Deployment information collection")

        for deployment in deployments:
            try:
                self._logger.info(f"Collecting deployment: {deployment} info")
                path = os.path.join(
                    f"{deployment_folder_path}",
                    f"{deployment}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    deployment_response = self._kube.describe_deployment(deployment, self._namespace)
                    write_yaml_to_file(deployment_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve deployment %s, caught %s Skipping...", deployment, e)

        self._logger.info("Deployment information collection completed")

    # Function to collect ingress information
    def collect_ingress_info(self, progress, ingresses=[]):

        # Create folder for ingresses if it does not exist
        ingress_folder_path = os.path.join(self._mustgather_folder, "ingresses")
        if not os.path.exists(ingress_folder_path):
            os.makedirs(ingress_folder_path)

        self._logger.info("Starting Ingress information collection")

        for ingress in ingresses:
            try:
                self._logger.info(f"Collecting ingress: {ingress} info")
                path = os.path.join(
                    f"{ingress_folder_path}",
                    f"{ingress}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    ingress_response = self._kube.describe_ingress(ingress, self._namespace)
                    write_yaml_to_file(ingress_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve ingress %s, caught %s Skipping...", ingress, e)

        self._logger.info("Ingress information collection completed")

    # Function to collect route or ingress information
    def collect_route_info(self, progress, routes=[]):

        # Create folder for routes if it does not exist
        route_folder_path = os.path.join(self._mustgather_folder, "routes")
        if not os.path.exists(route_folder_path):
            os.makedirs(route_folder_path)

        self._logger.info("Starting Routes information collection")

        for route in routes:
            try:
                self._logger.info(f"Collecting route: {route} info")
                path = os.path.join(
                    f"{route_folder_path}",
                    f"{route}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    route_response = self._kube.describe_route(route, self._namespace)
                    write_yaml_to_file(route_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve route %s, caught %s Skipping...", route, e)

        self._logger.info("Routes information collection completed")


    # Function to collect all HorizonalPodAutoscaler information
    def collect_hpa_info(self, progress, hpas=[]):
        # Create folder for hpas if it does not exist
        hpa_folder_path = os.path.join(self._mustgather_folder, "hpas")
        if not os.path.exists(hpa_folder_path):
            os.makedirs(hpa_folder_path)

        self._logger.info("Starting HPA information collection")

        for hpa in hpas:
            try:
                self._logger.info(f"Collecting HPA: {hpa} info")
                path = os.path.join(
                    f"{hpa_folder_path}",
                    f"{hpa}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    hpa_response = self._kube.describe_hpa(hpa, self._namespace)
                    write_yaml_to_file(hpa_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve HPA %s, caught %s Skipping...", hpa, e)

        self._logger.info("HPA information collection completed")

    # Function to collect all PodDisruptionBudget information
    def collect_pdb_info(self, progress, pdbs=[]):
        pdb_folder_path = os.path.join(self._mustgather_folder, "pdbs")
        if not os.path.exists(pdb_folder_path):
            os.makedirs(pdb_folder_path)

        self._logger.info("Starting PDB information collection")

        for pdb in pdbs:
            try:
                self._logger.info(f"Collecting PDB: {pdb} info")
                path = os.path.join(
                    f"{pdb_folder_path}",
                    f"{pdb}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Already collected in the previous step. Skipping...")
                else:
                    pdb_response = self._kube.describe_pdb(pdb, self._namespace)
                    write_yaml_to_file(pdb_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve PDB %s, caught %s Skipping...", pdb, e)

        self._logger.info("PDB information collection completed")

    # Function to collect Network Policy information
    def collect_network_policy_info(self, progress, network_policies=[]):

        # Create folder for network policies if it does not exist
        network_policy_folder_path = os.path.join(self._mustgather_folder, "network_policies")
        if not os.path.exists(network_policy_folder_path):
            os.makedirs(network_policy_folder_path)

        self._logger.info("Starting Network Policy information collection")

        for network_policy in network_policies:
            try:
                self._logger.info(f"Collecting network policy: {network_policy} info")
                path = os.path.join(
                    f"{network_policy_folder_path}",
                    f"{network_policy}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    network_policy_response = self._kube.describe_network_policy(network_policy, self._namespace)
                    write_yaml_to_file(network_policy_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve network policy %s, caught %s Skipping...", network_policy, e)

        self._logger.info("Network Policy information collection completed")

    # Function to collect service information
    def collect_service_info(self, progress, services=[]):

        # Create folder for services if it does not exist
        service_folder_path = os.path.join(self._mustgather_folder, "services")
        if not os.path.exists(service_folder_path):
            os.makedirs(service_folder_path)

        self._logger.info("Starting Service information collection")

        for service in services:
            try:
                self._logger.info(f"Collecting service: {service} info")
                path = os.path.join(
                    f"{service_folder_path}",
                    f"{service}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    service_response = self._kube.describe_service(service, self._namespace)
                    write_yaml_to_file(service_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve service %s, caught %s Skipping...", service, e)

        self._logger.info("Service information collection completed")

    # Function to collect pvcs
    def collect_pvc_info(self, progress, pvcs=list):

        # Create folder for pvcs if it does not exist
        pvc_folder_path = os.path.join(self._mustgather_folder, "pvcs")
        if not os.path.exists(pvc_folder_path):
            os.makedirs(pvc_folder_path)

        self._logger.info("Starting PVC information collection")

        for pvc in pvcs:
            try:
                self._logger.info(f"Collecting PVC: {pvc} info")
                path = os.path.join(
                    f"{pvc_folder_path}",
                    f"{pvc}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    pvc_response = self._kube.describe_pvc(pvc, self._namespace)
                    write_yaml_to_file(pvc_response, path)
            except Exception as e:
                self._logger.info("Unable to retrieve PVC %s, caught %s Skipping...", pvc, e)

        self._logger.info("PVC information collection completed")

    # Function to write CR file
    def write_cr_file(self, progress, name):
        try:
            self._logger.info("Collecting FNCM Custom Resource File")
            path = os.path.join(
                f"{self._mustgather_folder}",
                f"{self._cr_name}-cr.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                cr_response = self._kube.custom_resource

                self._logger.info(f"Collecting custom resource: {name} info")
                write_yaml_to_file(cr_response, path)
            self._logger.info("FNCM Custom Resource collection completed")

        except Exception as e:
            self._logger.info("Unable to retrieve CR, caught %s Skipping...", e)
    # Function to write AI Services CR file
    def write_ai_services_cr_file(self, progress, name=None):
        try:
            self._logger.info("Collecting AI Services Custom Resource File")
            
            # Get the CR from the cluster
            cr_response = self._kube.get_ai_services_cr(self._namespace, self._logger)
            
            if cr_response and "metadata" in cr_response:
                # Extract the actual CR name from the response
                actual_cr_name = cr_response["metadata"].get("name", name or "ccxaiservices")
                self._logger.info(f"Found AI Services CR: {actual_cr_name}")
                
                path = os.path.join(
                    f"{self._mustgather_folder}",
                    f"{actual_cr_name}-ai-services-cr.yaml",
                )
                
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    self._logger.info(f"Collecting AI Services custom resource: {actual_cr_name} info")
                    write_yaml_to_file(cr_response, path)
            else:
                self._logger.info("No AI Services CR found in namespace")
                
            self._logger.info("AI Services Custom Resource collection completed")

        except Exception as e:
            self._logger.info("Unable to retrieve AI Services CR, caught %s Skipping...", e)


    # Function to collect storage class information
    def collect_storage_class_info(self, progress, storage_classes=[]):

        # Create folder for storage if it does not exist
        storageclass_folder_path = os.path.join(self._mustgather_folder, "storageclasses")
        if not os.path.exists(storageclass_folder_path):
            os.makedirs(storageclass_folder_path)

        try:
            self._logger.info("Starting storage class information collection")

            for storage_class in storage_classes:
                self._logger.info(f"Collecting storage class: {storage_class} info")
                path = os.path.join(
                    f"{storageclass_folder_path}",
                    f"{storage_class}.yaml",
                )
                if os.path.isfile(path):
                    self._logger.info("Log already collected in the previous step. Skipping...")
                else:
                    storage_class_response = self._kube.describe_storage_class(storage_class)
                    write_yaml_to_file(storage_class_response, path)

            self._logger.info("Storage class information collection completed")

        except Exception as e:
            self._logger.info("Unable to retrieve storage classes, caught %s Skipping...", e)

    def collect_network_policy_templates(self,progress, operator_details):
        operator_pods = operator_details["pods"]

        try:
            self._logger.info("Starting network policy templates collection")
            policies_folder_path = os.path.join(self._mustgather_folder, "templates")
            if not os.path.exists(policies_folder_path):
                os.makedirs(policies_folder_path)
                self._logger.info(f"Creating Network Policy Templates folder: {policies_folder_path}")
            else:
                self._logger.info(f"Using existing Network Policy Templates folder: {policies_folder_path}")


            copied = self._kube.copy_files_from_pod(pod_name=operator_pods[0], namespace=self._namespace, src_path=f"/tmp/{self._namespace}/network-policies", dest_path=policies_folder_path)

            if not copied:
                return

            self._logger.info("Network policy templates collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve Network Policy Templates, caught %s Skipping...", e)
    
    def auto_apply_networkpolicy(self):
        content_egress_folder_path=os.path.join(self._mustgather_folder, "templates","Content","egress")
        content_ingress_folder_path=os.path.join(self._mustgather_folder, "templates","Content","ingress")
        ier_egress_folder_path=os.path.join(self._mustgather_folder, "templates","IER","egress")
        ier_ingress_folder_path=os.path.join(self._mustgather_folder, "templates","IER","ingress")
        iccsap_egress_folder_path=os.path.join(self._mustgather_folder, "templates","ICCSAP","egress")
        iccsap_ingress_folder_path=os.path.join(self._mustgather_folder, "templates","ICCSAP","ingress")
        ccxmo_egress_folder_path=os.path.join(self._mustgather_folder, "templates","CCXMO","egress")
        ccxmo_ingress_folder_path=os.path.join(self._mustgather_folder, "templates","CCXMO","ingress")
        # Get all yaml and yml files from the egress and ingress folders
        egress_files = list(Path(content_egress_folder_path).glob("*.yaml")) + list(Path(content_egress_folder_path).glob("*.yml")) + list(Path(ier_egress_folder_path).glob("*.yaml")) + list(Path(ier_egress_folder_path).glob("*.yml")) + list(Path(iccsap_egress_folder_path).glob("*.yaml")) + list(Path(iccsap_egress_folder_path).glob("*.yml")) + list(Path(ccxmo_egress_folder_path).glob("*.yaml")) + list(Path(ccxmo_egress_folder_path).glob("*.yml"))
        ingress_files = list(Path(content_ingress_folder_path).glob("*.yaml")) + list(Path(content_ingress_folder_path).glob("*.yml")) + list(Path(ier_ingress_folder_path).glob("*.yaml")) + list(Path(ier_ingress_folder_path).glob("*.yml")) + list(Path(iccsap_ingress_folder_path).glob("*.yaml")) + list(Path(iccsap_ingress_folder_path).glob("*.yml")) + list(Path(ccxmo_ingress_folder_path).glob("*.yaml")) + list(Path(ccxmo_ingress_folder_path).glob("*.yml"))
        if len(egress_files) == 0:
            self._logger.info(f"No egress network policy files found in FNCMNetworkPolicies/{self._namespace}")
            print()
            print(Panel.fit(Text(f"No egress network policy files found in FNCMNetworkPolicies/{self._namespace}/templates/*/egress/"), style="bold red"))
        if len(ingress_files) == 0:
            self._logger.info(f"No ingress network policy files found in CASNetworkPolicies/")
            print()
            print(Panel.fit(Text(f"No ingress network policy files found in FNCMNetworkPolicies/{self._namespace}/templates/*/ingress/"), style="bold red"))
        if len(egress_files) == 0 and len(ingress_files) == 0:
            return

         # Apply each network policy file

        print()
        print(Panel.fit(Text(f"Applying Egress and Ingress Network Policies"), style="cyan"))
        self._logger.info("Applying egress and ingress network policies")

        for file in egress_files:
            # Get Filename from path
            file_name = os.path.basename(file)
            self._logger.info(f"Applying network policy file: {str(file)}")
            try:
                applied = self._kube.apply_cluster_resource_files(resource_type='network_policy', resource_file=str(file), namespace=self._namespace)
                if not applied:
                    self._logger.info(f"Failed to apply network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Failed to apply network policy file: {str(file_name)}", style="bold red"))
                else:
                    self._logger.info(f"Successfully applied network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Successfully applied network policy file: {str(file_name)}", style="bold green"))
            except Exception as e:
                self._logger.info(f"Failed to apply network policy file {str(file_name)}: {e}")
                continue


        for file in ingress_files :
            # Get Filename from path
            file_name = os.path.basename(file)
            self._logger.info(f"Applying network policy file: {str(file)}")
            try:
                applied = self._kube.apply_cluster_resource_files(resource_type='network_policy', resource_file=str(file), namespace=self._namespace)
                if not applied:
                    self._logger.info(f"Failed to apply network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Failed to apply network policy file: {str(file_name)}", style="bold red"))
                else:
                    self._logger.info(f"Successfully applied network policy file: {str(file_name)}")
                    print()
                    print(Text(f"Successfully applied network policy file: {str(file_name)}", style="bold green"))
            except Exception as e:
                self._logger.info(f"Failed to apply network policy file {str(file_name)}: {e}")
                continue

        print()
        print(Panel.fit(Text(f"Successfully applied Egress and Ingress Network Policies", style="bold green")))
        self._logger.info("Applied egress and ingress network policies.")

    # Function to collect CPE information
    def collect_cpe_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for CPE if it does not exist
        cpe_folder_path = os.path.join(self._mustgather_folder, "cpe")
        if not os.path.exists(cpe_folder_path):
            os.makedirs(cpe_folder_path)

        cpe_pods = pods

        self._logger.info(f"Starting CPE Information Collection")

        try:
            if len(cpe_pods) == 0:
                return

            # Collect IBM Content Assistant Logs
            # Collection from the first pods as this shared in a PVC
            self._logger.info(f"Collecting IBM Content Assistant logs")
            path = os.path.join(
                f"{cpe_folder_path}",
                f"IBM Content Assistant",
            )
            if not os.path.exists(path):
                os.makedirs(path)

            self._kube.copy_files_from_pod(pod_name=cpe_pods[0], namespace=self._namespace,
                                                    src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/IBM Content Assistant/",
                                                    dest_path=path,
                                                    file_filter=f'{self._cr_name}-cpe*/*.log')


            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting CPE configuration files")
                path = os.path.join(
                    f"{cpe_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=cpe_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path)


            for pod in cpe_pods:
                self._logger.info(f"Collecting for CPE pod: {pod}")
                self.collect_pod_info(progress, cpe_folder_path, pod, init_containers, "cpe")

            self._logger.info(f"CPE information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve CPE, caught %s Skipping...", e)

    # Function to collect general pod information
    def collect_pod_info(self, progress, folder, pod, init_containers=list, component="", operator_type=None):
        # Create folder for pod info
        pod_path = os.path.join(f"{folder}", "pods", pod)
        if not os.path.exists(pod_path):
            os.makedirs(pod_path)

        # Python-based components — collect Python version and container logs instead of Java/Liberty
        python_components = ["genai_connector"]
        
        # Collect product version
        if component not in ["iccsap"]:
            self.get_component_version(pod, pod_path, progress)

        # For Python-based components, collect Python version instead of Java/Liberty
        if component in python_components:
            self._logger.info(f"Collecting Python version for component: {component}")
            self.get_python_version(pod, pod_path, progress)
            
            # Collect container logs directly (not Liberty logs)
            self._logger.info(f"Collecting container logs for component: {component}")
            self.get_container_logs(pod, pod_path, progress)
        else:
            # Java/Liberty-based components
            if component not in ["css", "operator", "iccsap"]:
                # Collect Liberty Version
                self.get_liberty_version(pod, pod_path, progress)

            # Collect Java Version
            self.get_java_version(pod, pod_path, progress)

            if component not in ["css", "operator", "iccsap"]:
                self.get_jvm_options(pod, pod_path, progress)

            # Collect Liberty Logs
            if component not in ["css", "operator", "iccsap"]:
                self._logger.info(f"Collecting liberty logs for component: {component}")

                self._kube.copy_files_from_pod(pod_name=pod, namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/logs/{pod}",
                                                        dest_path=pod_path,
                                                        file_filter=f'*')

        # Collect env variables (all components)
        self.get_environment_variables(pod, pod_path, progress)

        # Collect init-container logs
        for container in init_containers:
            self._logger.info(f"Collecting init-container logs: {container}")
            path = os.path.join(
                f"{pod_path}",
                f"{container}.log",
            )

            init_container_response = self._kube.get_init_container_logs(pod, self._namespace, container)
            write_log_to_file(init_container_response, path)

        # Collect pod yaml
        path = os.path.join(
            f"{pod_path}",
            f"{pod}.yaml",
        )

        cpe_response = self._kube.describe_pod(pod, self._namespace)
        write_yaml_to_file(cpe_response, path)

    def collect_ier_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for IER if it does not exist
        ier_folder_path = os.path.join(self._mustgather_folder, "ier")
        if not os.path.exists(ier_folder_path):
            os.makedirs(ier_folder_path)

        ier_pods = pods

        self._logger.info(f"Starting IER Information Collection")

        try:
            if len(ier_pods) == 0:
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting IER configuration files")
                path = os.path.join(
                    f"{ier_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=ier_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')

            for pod in ier_pods:
                self._logger.info(f"Collecting informations and logs for IER pod: {pod}")

                self.collect_pod_info(progress, ier_folder_path, pod, init_containers, "ier")

                self._logger.info(f"Collecting IER Plugin Configuration")

                # Collect plugin-cfg.xml
                command = ["cat", "/opt/ibm/wlp/usr/servers/defaultServer/logs/state/plugin-cfg.xml"]
                response = self._kube.pod_exec(pod, self._namespace, command)
                plugin_path = os.path.join(
                    f"{ier_folder_path}", "pods", f"{pod}", "plugin-cfg.xml"
                )
                with open(plugin_path, "w", encoding="utf8") as f:
                    f.write(response)

            self._logger.info(f"IER information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve IER, caught %s Skipping...", e)

    # Function to collect ICCSAP information
    def collect_iccsap_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for ICCSAP if it does not exist
        iccsap_folder_path = os.path.join(self._mustgather_folder, "iccsap")
        if not os.path.exists(iccsap_folder_path):
            os.makedirs(iccsap_folder_path)

        iccsap_pods = pods

        self._logger.info(f"Starting ICCSAP Information Collection")

        try:

            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting ICCSAP configuration files")
                path = os.path.join(
                    f"{iccsap_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=iccsap_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/IBM/iccsap/instance",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in iccsap_pods:
                self._logger.info(f"Collecting informations and logs for ICCSAP pod: {pod}")

                pod_path = os.path.join(f"{iccsap_folder_path}", "pods", pod)
                if not os.path.exists(pod_path):
                    os.makedirs(pod_path)

                self._kube.copy_files_from_pod(pod_name=pod, namespace=self._namespace,
                                                        src_path=f"/opt/IBM/iccsap/logs/{pod}",
                                                        dest_path=pod_path,
                                                        file_filter=f'*')


                self.collect_pod_info(progress, iccsap_folder_path, pod, init_containers, "iccsap")

            self._logger.info(f"ICCSAP information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve ICCSAP, caught %s Skipping...", e)
    # Function to collect CCXMO information
    def collect_ccxmo_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for CCXMO if it does not exist
        ccxmo_folder_path = os.path.join(self._mustgather_folder, "ccxmo")
        if not os.path.exists(ccxmo_folder_path):
            os.makedirs(ccxmo_folder_path)

        ccxmo_pods = pods

        self._logger.info(f"Starting CCXMO Information Collection")

        try:
            if len(ccxmo_pods) == 0:
                self._logger.info(f"No CCXMO pods found")
                return

            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting CCXMO configuration files")
                path = os.path.join(
                    f"{ccxmo_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=ccxmo_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in ccxmo_pods:
                self._logger.info(f"Collecting information and logs for CCXMO pod: {pod}")

                self.collect_pod_info(progress, ccxmo_folder_path, pod, init_containers, "ccxmo")

            self._logger.info(f"CCXMO information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve CCXMO, caught %s Skipping...", e)


    # Function to collect CSS information
    def collect_css_info(self, progress, collect_sensitive, pods=list, init_containers=list, deployment_num=""):

        # Create folder for CSS if it does not exist
        css_folder_path = os.path.join(self._mustgather_folder, "css", f"css-deploy-{deployment_num}")
        if not os.path.exists(css_folder_path):
            os.makedirs(css_folder_path)

        css_pods = pods

        self._logger.info(f"Starting CSS Information Collection: css-deploy-{deployment_num}")

        try:
            if len(css_pods) == 0:
                self._logger.info(f"No CSS pods found!")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting CSS configuration files")
                path = os.path.join(
                    f"{css_folder_path}",
                    f"Configuration",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=css_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/IBM/ContentSearchServices/CSS_Server/config",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in css_pods:
                self._logger.info(f"Collecting information and logs for CSS pod: {pod}")

                pod_path = os.path.join(f"{css_folder_path}", "pods", pod)
                if not os.path.exists(pod_path):
                    os.makedirs(pod_path)

                self._kube.copy_files_from_pod(pod_name=pod, namespace=self._namespace,
                                                src_path=f"/opt/IBM/ContentSearchServices/CSS_Server/log/{pod}",
                                                dest_path=pod_path,
                                                file_filter=f'*.log')


                self.collect_pod_info(progress, css_folder_path, pod, init_containers, "css")

            self._logger.info(f"CSS information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve CSS, caught %s Skipping...", e)

    # Function to collect GraphQL Information
    def collect_graphql_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for GraphQL if it does not exist
        graphql_folder_path = os.path.join(self._mustgather_folder, "graphql")
        if not os.path.exists(graphql_folder_path):
            os.makedirs(graphql_folder_path)

        graphql_pods = pods

        self._logger.info(f"Starting GraphQL Information Collection")

        try:
            if len(graphql_pods) == 0:
                self._logger.info(f"No GraphQL pods found")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting GraphQL configuration files")
                path = os.path.join(
                    f"{graphql_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=graphql_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')

            for pod in graphql_pods:
                self._logger.info(f"Collecting information and logs for GraphQL pod: {pod}")

                self.collect_pod_info(progress, graphql_folder_path, pod, init_containers, "graphql")

            self._logger.info(f"GraphQL information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve GraphQL, caught %s Skipping...", e)

    # Function to ExternalShare Information
    def collect_es_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for ExternalShare if it does not exist
        externalshare_folder_path = os.path.join(self._mustgather_folder, "es")
        if not os.path.exists(externalshare_folder_path):
            os.makedirs(externalshare_folder_path)

        externalshare_pods = pods

        self._logger.info(f"Starting ExternalShare Information Collection")

        try:
            if len(externalshare_pods) == 0:
                self._logger.info(f"No ExternalShare pods found")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting ExternalShare configuration files")
                path = os.path.join(
                    f"{externalshare_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=externalshare_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in externalshare_pods:
                self._logger.info(f"Collecting information and logs for ExternalShare pod: {pod}")

                self.collect_pod_info(progress, externalshare_folder_path, pod, init_containers, "es")

            self._logger.info(f"ExternalShare information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve ExternalShare, caught %s Skipping...", e)

    # Function to collect CMIS Information
    def collect_cmis_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for CMIS if it does not exist
        cmis_folder_path = os.path.join(self._mustgather_folder, "cmis")
        if not os.path.exists(cmis_folder_path):
            os.makedirs(cmis_folder_path)

        cmis_pods = pods

        self._logger.info(f"Starting CMIS Information Collection")

        try:
            if len(cmis_pods) == 0:
                self._logger.info(f"No CMIS pods found")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting CMIS configuration files")
                path = os.path.join(
                    f"{cmis_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=cmis_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in cmis_pods:
                self._logger.info(f"Collecting information and logs for CMIS pod: {pod}")

                self.collect_pod_info(progress, cmis_folder_path, pod, init_containers, "cmis")

            self._logger.info(f"CMIS information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve CMIS, caught %s Skipping...", e)

    # Function to collect TaskManager Information
    def collect_tm_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for TaskManager if it does not exist
        taskmanager_folder_path = os.path.join(self._mustgather_folder, "tm")
        if not os.path.exists(taskmanager_folder_path):
            os.makedirs(taskmanager_folder_path)

        taskmanager_pods = pods

        self._logger.info(f"Starting TaskManager Information Collection")

        try:
            if len(taskmanager_pods) == 0:
                self._logger.info(f"No TaskManager pods found")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting TaskManager configuration files")
                path = os.path.join(
                    f"{taskmanager_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=taskmanager_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in taskmanager_pods:
                self._logger.info(f"Collecting information and logs for TaskManager pod: {pod}")

                self.collect_pod_info(progress, taskmanager_folder_path, pod, init_containers, "tm")

            self._logger.info(f"TaskManager information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve TaskManager, caught %s Skipping...", e)

    # Function to collect Navigator information
    def collect_ban_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for Navigator if it does not exist
        navigator_folder_path = os.path.join(self._mustgather_folder, "ban")
        if not os.path.exists(navigator_folder_path):
            os.makedirs(navigator_folder_path)

        navigator_pods = pods

        self._logger.info(f"Starting Navigator Information Collection")

        try:
            if len(navigator_pods) == 0:
                self._logger.info(f"No Navigator pods found")
                return
            # Collect Configuration Files
            if collect_sensitive:
                self._logger.info(f"Collecting Navigator configuration files")
                path = os.path.join(
                    f"{navigator_folder_path}",
                    f"ConfigDropins",
                )
                if not os.path.exists(path):
                    os.makedirs(path)

                self._kube.copy_files_from_pod(pod_name=navigator_pods[0], namespace=self._namespace,
                                                        src_path=f"/opt/ibm/wlp/usr/servers/defaultServer/configDropins/overrides",
                                                        dest_path=path,
                                                        file_filter=f'*')


            for pod in navigator_pods:
                self._logger.info(f"Collecting information and logs for Navigator pod: {pod}")

                self.collect_pod_info(progress, navigator_folder_path, pod, init_containers, "ban")

            self._logger.info(f"Navigator information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve Navigator, caught %s Skipping...", e)

    # Function to collect GenAI Connector (IBM Content Assistant) information
    def collect_genai_connector_info(self, progress, collect_sensitive, pods=list, init_containers=list):

        # Create folder for GenAI Connector if it does not exist
        genai_connector_folder_path = os.path.join(self._mustgather_folder, "genai_connector")
        if not os.path.exists(genai_connector_folder_path):
            os.makedirs(genai_connector_folder_path)

        genai_pods = pods

        self._logger.info(f"Starting GenAI Connector Information Collection")

        try:
            if len(genai_pods) == 0:
                self._logger.info(f"No GenAI Connector pods found")
                return

            for pod in genai_pods:
                self._logger.info(f"Collecting information and logs for GenAI Connector pod: {pod}")
                self.collect_pod_info(progress, genai_connector_folder_path, pod, init_containers, "genai_connector")

            self._logger.info(f"GenAI Connector information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve GenAI Connector, caught %s Skipping...", e)

    # Function to collect Core MCP (AI Services) information
    def collect_rbac_info(self, progress, operator_details=dict):
        # Create folder for RBAC if it does not exist
        rbac_folder_path = os.path.join(self._mustgather_folder, "rbac")
        if not os.path.exists(rbac_folder_path):
            os.makedirs(rbac_folder_path)


        # Collect Role Information
        try:
            role = operator_details["role"]
            path = os.path.join(
                f"{rbac_folder_path}",
                f"role.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                role_response = self._kube.describe_role(role, self._namespace)
                if role_response is None or not role_response:
                    self._logger.info(f"Role {role} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(role_response, path)
        except Exception as e:
            self._logger.info("Unable to retrieve Role information, caught %s Skipping...", e)

        # Collect RoleBinding Information
        try:
            role_binding = operator_details["rolebinding"]
            path = os.path.join(
                f"{rbac_folder_path}",
                f"role_binding.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                role_binding_response = self._kube.describe_role_binding(role_binding, self._namespace)
                if role_binding_response is None or not role_binding_response:
                    self._logger.info(
                        f"RoleBinding {role_binding} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(role_binding_response, path)
        except Exception as e:
            self._logger.info("Unable to retrieve RoleBinding information, caught %s Skipping...", e)

        # Collect ServiceAccount Information
        try:
            service_account = operator_details["service_account"]
            path = os.path.join(
                f"{rbac_folder_path}",
                f"service_account.yaml",
            )
            if os.path.isfile(path):
                self._logger.info("Log already collected in the previous step. Skipping...")
            else:
                service_account_response = self._kube.describe_service_account(service_account, self._namespace)
                if service_account_response is None or not service_account_response:
                    self._logger.info(
                        f"ServiceAccount {service_account} not found in namespace {self._namespace}. Skipping...")
                else:
                    write_yaml_to_file(service_account_response, path)
        except Exception as e:
            self._logger.info("Unable to retrieve ServiceAccount information, caught %s Skipping...", e)

    # Function to collect Operator information (Content or AI Services)
    def collect_operator_info(self, progress, collect_sensitive, operator_details=dict):
        
        # Determine operator type and create appropriate folder
        operator_type = operator_details.get("operator_type", "content")
        if operator_type == "ai-services":
            operator_folder_name = "ai-services-operator"
            operator_display_name = "AI Services Operator"
        else:
            operator_folder_name = "content-assistant-operator"
            operator_display_name = "Content Operator"
        
        # Create folder for operator if it does not exist
        operator_folder_path = os.path.join(self._mustgather_folder, "operator", operator_folder_name)
        if not os.path.exists(operator_folder_path):
            os.makedirs(operator_folder_path)

        operator_pods = operator_details["pods"]

        self._logger.info(f"Starting {operator_display_name} Information Collection")

        try:
            # Collect Deployment Information
            deployment = operator_details["deployment"]
            self._logger.info(f"Collecting information on deployment: {deployment}")
            path = os.path.join(
                f"{operator_folder_path}",
                f"{deployment}.yaml",
            )

            deployment_response = self._kube.describe_deployment(deployment, self._namespace)
            write_yaml_to_file(deployment_response, path)

            deployment_type = operator_details["type"]

            if deployment_type == "OLM":

                # Collect CSV Information
                csv = operator_details["installedCSV"]
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"cluster-service-version.yaml",
                )

                csv_response = self._kube.describe_csv(csv, self._namespace)
                write_yaml_to_file(csv_response, path)


                # Collect Subscription Information
                subscription = operator_details["subscription"]
                self._logger.info(f"Collecting information on subscription: {subscription}")
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"subscription.yaml",
                )

                subscription_response = self._kube.describe_subscription(subscription, self._namespace)
                write_yaml_to_file(subscription_response, path)

                # Collect CatalogSource Information

                catalogsource = operator_details["catalogSource"]
                catalogsource_namespace = operator_details["sourceNamespace"]
                self._logger.info(f"Collecting information on catalogsource: {catalogsource}")
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"catalogsource.yaml",
                )

                catalogsource_response = self._kube.describe_catalogsource(catalogsource, catalogsource_namespace)
                write_yaml_to_file(catalogsource_response, path)

                # Collect OperatorGroup Information
                operator_group = operator_details["operatorGroup"]
                self._logger.info(f"Collecting information on operator group: {operator_group}")
                path = os.path.join(
                    f"{operator_folder_path}",
                    f"operatorgroup.yaml",
                )

                operator_group_response = self._kube.describe_operator_group(operator_group, self._namespace)
                write_yaml_to_file(operator_group_response, path)
            
            elif deployment_type == "HELM":
                # Collect Helm release information
                self._logger.info(f"Detected Helm installation for {operator_display_name}")
                
                # Get Helm release name from operator details
                helm_release = operator_details.get("helm_release", deployment)
                helm_namespace = operator_details.get("helm_namespace", self._namespace)
                
                self._logger.info(f"Collecting Helm values for release: {helm_release} in namespace: {helm_namespace}")
                
                # Collect Helm values using helm commands
                try:
                    import subprocess
                    
                    # Get the Helm values using helm get values command
                    self._logger.info(f"Running: helm get values {helm_release} -n {helm_namespace} --all")
                    values_cmd = [
                        "helm", "get", "values", helm_release,
                        "-n", helm_namespace,
                        "--all"
                    ]
                    
                    values_result = subprocess.run(values_cmd, capture_output=True, text=True, timeout=30)
                    
                    if values_result.returncode == 0 and values_result.stdout.strip():
                        # Save values.yaml
                        values_path = os.path.join(operator_folder_path, "helm-values.yaml")
                        with open(values_path, "w", encoding="utf8") as f:
                            f.write(values_result.stdout)
                        self._logger.info(f"✓ Saved Helm values to: {values_path}")
                    else:
                        error_msg = values_result.stderr if values_result.stderr else "No output returned"
                        self._logger.warning(f"Could not retrieve Helm values for {helm_release}: {error_msg}")
                    
                    # Also get the full Helm release manifest
                    self._logger.info(f"Running: helm get manifest {helm_release} -n {helm_namespace}")
                    manifest_cmd = [
                        "helm", "get", "manifest", helm_release,
                        "-n", helm_namespace
                    ]
                    
                    manifest_result = subprocess.run(manifest_cmd, capture_output=True, text=True, timeout=30)
                    
                    if manifest_result.returncode == 0 and manifest_result.stdout.strip():
                        manifest_path = os.path.join(operator_folder_path, "helm-manifest.yaml")
                        with open(manifest_path, "w", encoding="utf8") as f:
                            f.write(manifest_result.stdout)
                        self._logger.info(f"✓ Saved Helm manifest to: {manifest_path}")
                    else:
                        error_msg = manifest_result.stderr if manifest_result.stderr else "No output returned"
                        self._logger.warning(f"Could not retrieve Helm manifest for {helm_release}: {error_msg}")
                    
                    # Get Helm release notes
                    self._logger.info(f"Running: helm get notes {helm_release} -n {helm_namespace}")
                    notes_cmd = [
                        "helm", "get", "notes", helm_release,
                        "-n", helm_namespace
                    ]
                    
                    notes_result = subprocess.run(notes_cmd, capture_output=True, text=True, timeout=30)
                    
                    if notes_result.returncode == 0 and notes_result.stdout.strip():
                        notes_path = os.path.join(operator_folder_path, "helm-notes.txt")
                        with open(notes_path, "w", encoding="utf8") as f:
                            f.write(notes_result.stdout)
                        self._logger.info(f"✓ Saved Helm notes to: {notes_path}")
                        
                except subprocess.TimeoutExpired:
                    self._logger.warning(f"Timeout while collecting Helm information for {helm_release}")
                except FileNotFoundError:
                    self._logger.warning(f"Helm CLI not found. Please ensure 'helm' is installed and in PATH")
                except Exception as e:
                    self._logger.warning(f"Error collecting Helm values for {helm_release}: {e}")

            # Collect Configuration Files
            if len(operator_pods) == 0:
                self._logger.info(f"No Content Operator pods found")
                return

            for pod in operator_pods:

                pod_path = os.path.join(f"{operator_folder_path}", "pods", pod)
                if not os.path.exists(pod_path):
                    os.makedirs(pod_path)

                self._logger.info(f"Collecting information for Content Operator pod: {pod}")

                init_containers = operator_details["init_containers"]

                self.collect_pod_info(progress, operator_folder_path, pod, init_containers, "operator", operator_type)

            # Collect operator container logs (stdout/stderr via Kubernetes API).
            # The CAS operator is Go-based (/manager entrypoint) and writes all logs
            # to stdout — there are no on-disk Ansible runner artifacts.
            self._logger.info(f"Collecting {operator_display_name} container logs")
            logs_folder = os.path.join(operator_folder_path, "logs")
            if not os.path.exists(logs_folder):
                os.makedirs(logs_folder)
            self.get_container_logs(operator_pods[0], operator_folder_path, progress)

            self._logger.info(f"{operator_display_name} information collection completed.")

        except Exception as e:
            self._logger.info("Unable to retrieve Content Operator, caught %s Skipping...", e)

    # Function to collect environment variables
    def get_environment_variables(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting environment variables")
            command = ["printenv"]
            env_vars = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "environment_variables.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(env_vars)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )

    # Function to collect Product Version
    def get_component_version(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting component version for {pod}")
            command = ["cat", "/opt/ibm/version.txt"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )

    # Function to collect Liberty Version
    def get_liberty_version(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting liberty version for {pod}")
            command = ["/opt/ibm/wlp/bin/server", "version"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "liberty_version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )

    # Function to collect jvm.options
    def get_jvm_options(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting jvm options for {pod}")
            command = ["cat", "/opt/ibm/wlp/usr/servers/defaultServer/jvm.options"]
            options = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "jvm_options.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(options)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )

    # Function to collect Java Version
    def get_java_version(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting IBM Java version for {pod}")
            command = ["java", "-version"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "java_version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to copy from pod, caught %s Skipping...", e
            )

    # Function to collect Python Version (for AI Services components)
    def get_python_version(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting Python version for {pod}")
            command = ["python3", "--version"]
            version = self._kube.pod_exec(pod, self._namespace, command)
            local_path = os.path.join(
                f"{folder_path}", "python_version.txt"
            )
            with open(local_path, "w", encoding="utf8") as f:
                f.write(version)

        except Exception as e:
            self._logger.info(
                "Unable to collect Python version, caught %s Skipping...", e
            )

    # Function to collect container logs directly (for AI Services components)
    def get_container_logs(self, pod, folder_path, progress):
        try:
            self._logger.info(f"Collecting container logs for {pod}")
            
            # Create logs folder if it doesn't exist
            logs_folder = os.path.join(folder_path, "logs")
            if not os.path.exists(logs_folder):
                os.makedirs(logs_folder)
            
            # Get logs from all containers in the pod
            container_logs = self._kube.get_pod_logs(pod, self._namespace)
            
            # Save logs for each container
            for container_name, logs in container_logs.items():
                log_file = os.path.join(logs_folder, f"{container_name}.log")
                with open(log_file, "w", encoding="utf8") as f:
                    f.write(logs)
                self._logger.info(f"Saved logs for container: {container_name}")

        except Exception as e:
            self._logger.info(
                "Unable to collect container logs, caught %s Skipping...", e
            )
