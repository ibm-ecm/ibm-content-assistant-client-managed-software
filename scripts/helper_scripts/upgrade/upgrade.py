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
import os.path
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from rich import print
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from time import sleep

from ..utilities import kubernetes_utilites as k
from ..utilities.prerequisites_utilites import zip_folder, write_yaml_to_file
from ..utilities.utilities import replace_namespace_in_file, create_tmp_folder, is_key_present, update_value_by_path, \
    find_keys_and_structures, delete_key_by_path
from ..generate.generate_metrics import GenerateMetrics


# Class to handle upgrade operator and deployment related functionalities
class Upgrade:
    def __init__(self, console, setup=None, logger=None, silent=False, required_files=None, selected_license=None):
        self._logger = logger
        self._console = console
        self._silent = silent
        self._kube = k.KubernetesUtilities(logger)
        self._setup = setup
        self._namespace = self._setup.namespace
        self._cr_present = True
        self._operator_present = True
        self._selected_license = selected_license

        # checking if custom resource file exists
        cr_details = self._kube.get_deployment_cr(namespace=self._namespace, logger=self._logger)

        if not cr_details:
            self._cr_present = False
            self._logger.info(f"No Custom Resource file found in '{self._namespace}'.")

        # checking if operator exists
        # Check for subscription regardless of platform (OLM can be used on both OCP and CNCF)
        self._subscription_details = self._kube.get_subscription(namespace=self._namespace)

        # Collect Operator details
        operator_deployment = "ibm-content-assistant-operator"
        self._operator_details = self._kube.get_operator_details(self._namespace, operator_deployment)
        if not self._operator_details:
            self._operator_present = False

        # Deployment Details
        self._deployment_details = {}

        # Version Details
        self._version_details = {}

        # Custom Resource Details
        self._cr_details = {}

        self._apps_v1_api = self._kube.apps_v1
        self._core_v1_api = self._kube.core_v1
        self._custom_api = self._kube.custom_api

        self.required_file_paths = {}
        for file in required_files:
            file_name = file.split("/")[-1]
            self.required_file_paths[file_name] = file

        # Tmp File paths for the resources
        create_tmp_folder()
        modified_files = [
            "cluster_role_binding.yaml",
            "catalogsource.yaml",
            "operator_group.yaml",
            "subscription.yaml",
            "operator.yaml"
        ]
        self.tmp_file_paths = {}
        for file in modified_files:
            self.tmp_file_paths[file] = os.path.join(os.getcwd(), ".tmp", file)

        self._download_location = os.path.join(os.getcwd(), "CASUpgrade", self._namespace)
        self._cr_template_save_location = os.path.join(os.getcwd(), "CASUpgrade", self._namespace, "CustomResources")
        self._current_cr_template_save_location = ""
        self._updated_cr_template_save_location = ""
        self._networkwork_policy_save_location = os.path.join(os.getcwd(), "CASUpgrade", self._namespace, "NetworkPolicies")
        self._networkwork_policy_ingress_save_location= os.path.join(self._networkwork_policy_save_location, "Ingress")
        self._networkwork_policy_egress_save_location = os.path.join(self._networkwork_policy_save_location, "Egress")
        self._metrics_save_location = os.path.join(os.getcwd(), "CASUpgrade", self._namespace, "Metrics")

        if "catalogType" in self._operator_details:
            self._catalog_type = self._operator_details["catalogType"]

            if self._operator_details["catalogType"] != "Private":
                self._catalog_namespace = "openshift-marketplace"
            else:
                self._catalog_namespace = self._namespace
        else:
            self._catalog_type = "Private"
            self._catalog_namespace = self._namespace

        # Determine deployment type based on catalog type (not platform)
        # Helm is the default for both OCP and CNCF platforms
        if self._catalog_type != "Private":
            # Global catalog indicates OLM deployment
            self._deployment_type = "olm"
            self._task_numbers = {
                "UpgradeSetup": 3,
                "Upgrade": 4,
            }
            if "type" in self._operator_details:
                if self._operator_details["type"] == "YAML":
                    self._remove_yaml = True
                    self._task_numbers["CleanYaml"] = 3
                else:
                    self._remove_yaml = False
            else:
                self._remove_yaml = False
        else:
            # Private catalog or Helm deployment
            self._deployment_type = "helm"
            self._remove_yaml = False
            self._task_numbers = {
                "UpgradeSetup": 4,
                "Upgrade": 3,
            }

        self._updates_list = []

    @property
    def download_location(self):
        return self._download_location

    @property
    def cr_template_save_location(self):
        return self._cr_template_save_location

    @property
    def current_cr_template_save_location(self):
        return self._current_cr_template_save_location

    @property
    def updated_cr_template_save_location(self):
        return self._updated_cr_template_save_location

    @property
    def updates_list(self):
        return self._updates_list

    @property
    def deployment_details(self):
        return self._deployment_details

    @deployment_details.setter
    def deployment_details(self, value):
        self._deployment_details = value

    @property
    def version_details(self):
        return self._version_details

    @version_details.setter
    def version_details(self, value):
        self._version_details = value

    @property
    def remove_yaml(self):
        return self._remove_yaml

    @property
    def task_numbers(self):
        return self._task_numbers

    @property
    def deployment_type(self):
        return self._deployment_type

    @property
    def operator_details(self):
        return self._operator_details

    @property
    def catalog_namespace(self):
        return self._catalog_namespace

    @catalog_namespace.setter
    def catalog_namespace(self, value):
        self._catalog_namespace = value

    @property
    def catalog_type(self):
        return self._catalog_type

    @catalog_type.setter
    def catalog_type(self, value):
        self._catalog_type = value

    @property
    def selected_license(self):
        return self._selected_license

    @selected_license.setter
    def selected_license(self, value):
        self._selected_license = value
        self._logger.info(f"License model updated to: {value}")

    # Function to remove yaml style deployment
    def remove_yaml_deployment(self, progress, task):
        # Number of tasks = 4
        SLEEP_TIMER = 5
        if "role" not in self._operator_details:
            role = None
        else:
            if self._operator_details["role"]:
                role = self._operator_details["role"]
            else:
                role = None

        if "rolebinding" not in self._operator_details:
            rolebinding = None
        else:
            if self._operator_details["rolebinding"]:
                rolebinding = self._operator_details["rolebinding"]
            else:
                rolebinding = None

        if "service_account" not in self._operator_details:
            service_account = None
        else:
            if self._operator_details["service_account"]:
                service_account = self._operator_details["service_account"]
            else:
                service_account = None

        progress.log(Panel.fit("Starting IBM Content Assistant Operator YAML Deployment Cleanup", style="cyan"))
        progress.log()
        self._logger.info(f"Starting clean-up of IBM Content Assistant Operator YAML Deployment.")
        try:
            progress.log()
            progress.log("Deleting Operator Deployment...")
            self._logger.info(f"Deleting Operator deployment.")
            self._kube.delete_operator_deployment(namespace=self._namespace)
            sleep(SLEEP_TIMER)
            progress.advance(task)

            progress.log()
            progress.log("Deleting Operator RoleBinding...")
            self._logger.info(f"Deleting Operator role-binding.")
            if rolebinding:
                self._kube.delete_role_binding(namespace=self._namespace, name=rolebinding)
            else:
                progress.log()
                progress.log(Panel.fit("Rolebinding not found", style="bold red"))
                self._logger.info(f"Rolebinding: {rolebinding} not found.")
            sleep(SLEEP_TIMER)
            progress.advance(task)

            progress.log()
            progress.log("Deleting Operator Role...")
            self._logger.info(f"Deleting Operator role.")
            if role:
                self._kube.delete_role(namespace=self._namespace, name=role)
            else:
                progress.log()
                progress.log(Panel.fit("Role not found", style="bold red"))
                self._logger.info(f"Role: {role} not found.")
            sleep(SLEEP_TIMER)
            progress.advance(task)

            progress.log()
            progress.log("Deleting Operator Service Account...")
            self._logger.info(f"Deleting Operator service account.")
            if service_account:
                self._kube.delete_service_account(namespace=self._namespace, name=service_account)
            else:
                progress.log()
                progress.log(Panel.fit("Service Account not found", style="bold red"))
                self._logger.info(f"Service Account: {service_account} not found.")
            sleep(SLEEP_TIMER)
            progress.advance(task)

            progress.log(Panel.fit("IBM Content Assistant Operator YAML Deployment Cleanup Completed", style="bold green"))
            progress.log()
            self._logger.info(f"Completed clean up of IBM Content Assistant Operator YAML Deployment")

        except Exception as e:
            progress.log(Text(f"Error occurred while removing the resources: {e}", style="bold red"))
            self._logger.info(f"Error occurred while removing the resources: {e}")

    def apply_cncf(self, progress, task):
        try:
            # Number of Tasks = 4
            progress.log(Panel.fit("Starting CRD and Permission Upgrade", style="cyan"))
            progress.log()
            self._logger.info(f"Starting CRD and Permission Upgrade")

            # Apply the CRD
            progress.log(f"Applying/Patching Custom Resource Definition")
            progress.log()
            self._logger.info(f"Applying/Patching Custom Resource Definition")
            self._kube.apply_cluster_resource_files(
                resource_file=self.required_file_paths["cas_v1_cas_crd.yaml"],
                resource_type="Custom Resource Definition")
            progress.update(task, advance=1)

            # Apply the Cluster Role
            progress.log(f"Applying/Patching Cluster Role")
            progress.log()
            self._logger.info(f"Applying/Patching Custom Role")
            self._kube.apply_cluster_resource_files(
                resource_file=self.required_file_paths["service_account.yaml"],
                resource_type="Service Account", namespace=self._setup.namespace)
            progress.update(task, advance=1)

            # Apply the Role
            progress.log(f"Applying/Patching Role")
            progress.log()
            self._logger.info(f"Applying/Patching Role")
            self._kube.apply_cluster_resource_files(
                resource_file=self.required_file_paths["role.yaml"], resource_type="Role",
                namespace=self._setup.namespace)
            progress.update(task, advance=1)

            # Apply the Role Binding
            progress.log(f"Applying/Patching Role Binding")
            progress.log()
            self._logger.info(f"Applying/Patching Role Binding")
            self._kube.apply_role_binding(
                namespace=self._setup.namespace, resource_file=self.required_file_paths["role_binding.yaml"])
            progress.update(task, advance=1)

            progress.log(Panel.fit("CRD and Permission Upgrade Completed", style="bold green"))
            progress.log()
            self._logger.info(f"CRD and Permission Upgrade Completed")
        except Exception as e:
            progress.log(Text(f"Error occurred while applying the resources: {e}", style="bold red"))
            self._logger.info(f"Error occurred while applying the resources: {e}")

    def apply_olm(self, progress, task):
        # Number of tasks = 3
        try:
            progress.log(Panel.fit("Starting OLM Upgrade", style="cyan"))
            progress.log()
            self._logger.info(f"Starting OLM Upgrade")
            if self._catalog_type == "Private":
                self._catalog_namespace = self._namespace
                progress.log(f"Using private catalog namespace: {self._catalog_namespace}")
                progress.log()
                self._logger.info(f"Using private catalog namespace: {self._catalog_namespace}")

            else:
                progress.log(f"Using global catalog namespace (GCN): {self._catalog_namespace}")
                progress.log()
                self._logger.info(f"Using global catalog namespace (GCN): {self._catalog_namespace}")
            replace_namespace_in_file(project_name=self._catalog_namespace,
                                      input_file=self.required_file_paths["catalogsource.yaml"],
                                      output_file=self.tmp_file_paths["catalogsource.yaml"],
                                      resource_type="catalog source")

            progress.log(f"Applying/Patching Catalog Source")
            progress.log()
            self._logger.info(f"Applying/Patching Catalog Source")

            self._kube.apply_cluster_resource_files(
                resource_file=self.tmp_file_paths["catalogsource.yaml"],
                namespace=self._catalog_namespace, resource_type="Catalog Source")
            progress.update(task, advance=1)

            retries = 0
            catalogsource_name = "ibm-content-assistant-operator-catalog"
            progress.log(f"Waiting for IBM Content Assistant Operator Catalog Pod to start")
            progress.log()
            self._logger.info(f"Waiting for IBM Content Assistant Operator Catalog Pod to start")
            while retries < 80:
                catalog_ready = self._kube.check_catalogsource_rollout_status(catalogsource_name,
                                                                              self._catalog_namespace)

                if catalog_ready:
                    progress.log(
                        Text(f"IBM Content Assistant Operator Catalog Pod is running.", style="bold green"))
                    progress.log()
                    break
                else:
                    retries = retries + 1
                    progress.log(f"IBM Content Assistant Operator deployment in progress ({retries + 1}/40) ")
                    progress.log()
                    sleep(5)

            if retries == 80:
                progress.log(Text("Timeout Waiting for IBM Content Assistant Operator Catalog pod to start",
                                  style="bold red"))
                progress.log()

                progress.log("Please check the status of Pod by issuing the below command:")
                progress.log()
                progress.log(Syntax(
                    f"kubectl describe pod $(kubectl get pod -n {self._catalog_namespace} | grep ibm-content-assistant-operator-catalog | awk '{{print $1}}') -n ${self._catalog_namespace}",
                    "bash"))

            progress.update(task, advance=1)

            # Collect Operator Group
            self._logger.info(f"Creating operator group.")
            operator_group = self._kube.get_operator_group(self._namespace)
            if operator_group:
                progress.log(f"Operator Group already exists")
                progress.log()
                self._logger.info(f"Operator Group already exists")
            else:
                progress.log("Applying/Patching Operator Group")
                progress.log()
                self._logger.info(f"Applying/Patching Operator Group")
                replace_namespace_in_file(project_name=self._namespace,
                                          input_file=self.required_file_paths["operator_group.yaml"],
                                          output_file=self.tmp_file_paths["operator_group.yaml"],
                                          resource_type="operator group")

                self._kube.apply_cluster_resource_files(
                    resource_file=self.tmp_file_paths["operator_group.yaml"],
                    namespace=self._namespace,
                    resource_type="Operator Group")
            progress.update(task, advance=1)

            progress.log(Panel.fit("OLM Installation Completed", style="bold green"))
            progress.log()
            self._logger.info(f"OLM Installation Completed")
        except Exception as e:
            progress.log(Text(f"Error occurred while applying the resources: {e}", style="bold red"))
            self._logger.info(f"Error occurred while applying the resources: {e}")

    def wait_for_operator(self, progress, task):
        try:
            # Initialize attempts counter
            # Number of tasks = 1
            attempts = 0
            retries = 0
            deployment_name = self._operator_details["deployment"]
            progress.log(f"Checking rollout status of IBM Content Assistant Operator deployment")
            progress.log()
            self._logger.info(f"Checking rollout status of IBM Content Assistant Operator deployment")
            while retries < 40:

                updated = self._kube.check_deployment_rollout_status(deployment_name, self._namespace)

                if updated:
                    progress.log(
                        Text(f"IBM Content Assistant Operator Pod is running.", style="bold green"))
                    progress.log()
                    self._logger.info(f"IBM Content Assistant Operator Pod is running.")
                    progress.update(task, advance=1)
                    break
                else:
                    retries = retries + 1
                    progress.log(f"IBM Content Assistant Operator upgrade in progress ({retries + 1}/40) ")
                    progress.log()
                    sleep(15)

            if retries == 40:
                progress.log(Text("Timeout Waiting for IBM Content Assistant Operator pod to start",
                                  style="bold red"))
                progress.log()
                self._logger.info(f"Timeout Waiting for IBM Content Assistant Operator pod to start")

                progress.log("Please check the status of Pod by issuing the below command:")
                progress.log()
                progress.log(Syntax(
                    f"kubectl describe pod $(kubectl get pods -n {self._namespace} -l 'name=ibm-content-assistant-operator' | awk '{{print $1}}') -n {self._namespace}",
                    "bash"))
                exit()

            progress.log(Panel.fit("IBM Content Assistant Operator Upgrade Completed", style="bold green"))
            progress.update(task, advance=1)
        except Exception as e:
            progress.log(Text(f"Error occurred while applying the resources: {e}", style="bold red"))
            progress.log()
            self._logger.info(f"Error occurred while waiting for the operator: {e}")

    def upgrade_operator_olm(self, progress, task):
        # Number of tasks = 2

        progress.log(Panel.fit("Starting IBM Content Assistant Operator Upgrade", style="cyan"))
        progress.log()
        self._logger.info(f"Starting IBM Content Assistant Operator Upgrade")

        progress.log(f"Scaling down older operator pod before upgrading")
        progress.log()
        self._logger.info(f"Scaling down older operator pod prior to the upgrade")

        # Scale down older operator pod before upgrading
        # If moving from Yaml deployment, the deployment will not exist
        if not self.remove_yaml:
            operator_deployment = self._operator_details["deployment"]
            self._kube.scale_operator_deployment(namespace=self._namespace, deployment_name=operator_deployment,
                                                 scale="down")

        progress.log(f"Applying/Patching Subscription")
        progress.log()
        self._logger.info(f"Applying/Patching the subscription")

        if self._catalog_type == "Private":
            replace_namespace_in_file(project_name=self._namespace,
                                      input_file=self.required_file_paths["subscription.yaml"],
                                      output_file=self.tmp_file_paths["subscription.yaml"],
                                      resource_type="subscription",
                                      private=True)
            progress.log(f"Using private catalog namespace: {self._namespace}")
            progress.log()
            self._logger.info(f"Using private catalog namespace: {self._namespace}")
            progress.update(task, advance=1)
        else:
            replace_namespace_in_file(project_name=self._namespace,
                                      input_file=self.required_file_paths["subscription.yaml"],
                                      output_file=self.tmp_file_paths["subscription.yaml"],
                                      resource_type="subscription")
            progress.log(f"Using global catalog namespace (GCN): {self._catalog_namespace}")
            self._logger.info(f"Using global catalog namespace (GCN): {self._catalog_namespace}")
            progress.update(task, advance=1)

        self._logger.info(f"Applying the custom resource files")
        self._kube.apply_cluster_resource_files(
            resource_file=self.tmp_file_paths["subscription.yaml"],
            namespace=self._namespace,
            resource_type="Subscription")

        progress.update(task, advance=1)

        self.wait_for_operator(progress, task)

    # Function to install operator on CNCF
    def upgrade_operator_cncf(self, progress, task):
        # Number of tasks = 2
        progress.log(Panel.fit("Starting IBM Content Assistant Operator Upgrade", style="cyan"))
        progress.log()
        self._logger.info(f"Starting IBM Content Assistant Operator Upgrade")

        shutil.copy(self.required_file_paths["operator.yaml"], self.tmp_file_paths["operator.yaml"])
        with open(self.tmp_file_paths["operator.yaml"], 'r') as file:
            content = file.read()

        progress.log("Setting license acceptance to 'accept' in the operator file")
        progress.log()
        self._logger.info(f"Setting license acceptance to 'accept' in the operator file")

        # Update the 'cas_license' value to 'accept' if present in the operator file
        content = re.sub(r'cas_license:\n  value:.*', 'cas_license:\n  value: accept', content)

        # Write the modified content back to the temporary operator file
        with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
            file.write(content)

        with open(self.tmp_file_paths["operator.yaml"], 'r') as file:
            content = file.read()
        registry_in_file = "icr.io"

        if self._setup.private_registry_valid:
            progress.log("IBM Content Assistant Operator is being upgraded using a private registry")
            progress.log()
            self._logger.info(f"IBM Content Assistant Operator is being upgraded using a private registry")
            pattern = re.compile(re.escape(registry_in_file) + r'\b')
            replacement = self._setup.private_registry_full_server
            content = pattern.sub(replacement, content)

            # Write the modified content back to the temporary operator file
            with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
                file.write(content)
        else:
            progress.log("IBM Content Assistant Operator is being upgraded using the IBM Entitlement Registry")
            progress.log()
            self._logger.info(f"IBM Content Assistant Operator is being upgraded using the IBM Entitlement Registry")
            if self._setup.runtime_mode == "dev":
                progress.log("Using dev registry for IBM Content Assistant Operator upgrade")
                progress.log()
                self._logger.info(f"Using dev registry for IBM Content Assistant Operator upgrade")
                pattern = re.compile(re.escape(registry_in_file + '/cpopen') + r'\b')
                replacement = "preprod.icr.io" + '/cpopen'
                content = pattern.sub(replacement, content)

                # Write the modified content back to the temporary operator file
                with open(self.tmp_file_paths["operator.yaml"], 'w') as file:
                    file.write(content)

        progress.log(f"Applying/Patching IBM Content Assistant Operator Deployment")
        progress.log()
        self._logger.info(f"Applying/Patching IBM Content Assistant Operator Deployment")

        self._kube.apply_cluster_resource_files(
            resource_file=self.tmp_file_paths["operator.yaml"], resource_type="Deployment",
            namespace=self._namespace)

        progress.update(task, advance=1)

        self.wait_for_operator(progress, task)

    def convert_keys_to_camel_case(self, obj):
        KEYS_TO_REMOVE = {
            "status",
            "managedFields",
            "creationTimestamp",
            "ownerReferences",
        }

        def snake_to_camel(snake_str):
            components = snake_str.lstrip('_').split('_') 
            return components[0] + ''.join(x.title() for x in components[1:])

        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                key_no_underscore = k.lstrip('_')
                camel_key = snake_to_camel(key_no_underscore)

                if camel_key in KEYS_TO_REMOVE or v is None:
                    continue

                new_dict[camel_key] = self.convert_keys_to_camel_case(v)
            return new_dict
        elif isinstance(obj, list):
            return [self.convert_keys_to_camel_case(i) for i in obj if i is not None]
        else:
            return obj

    def clean_networkpolicies(self, network_policy_path):
        np_files = list(Path(network_policy_path).glob("*.yaml")) + list(Path(network_policy_path).glob("*.yml"))
        for file in np_files:
            with open(file, 'r') as f:
                data = yaml.safe_load(f)
            np_case_converted = self.convert_keys_to_camel_case(data)
                            # Remove unused sections from the CR
            remove_fields = ["creationTimestamp",
                                "generation",
                                "resourceVersion",
                                "uid",
                                "managedFields"]
            for field in remove_fields:
                if field in np_case_converted["metadata"].keys():
                    del np_case_converted["metadata"][field]
            if "annotations" in np_case_converted["metadata"].keys():
                if 'kubectl.kubernetes.io/last-applied-configuration' in np_case_converted["metadata"]["annotations"]:
                    del np_case_converted["metadata"]["annotations"]['kubectl.kubernetes.io/last-applied-configuration']
                if not np_case_converted["metadata"]["annotations"]:
                    del np_case_converted["metadata"]["annotations"]
            with open(file, 'w') as f:
                yaml.safe_dump(np_case_converted, f, default_flow_style=False, sort_keys=False)

    def collect_network_policy_info(self):
        resource_type_dict = self._kube.list_namespace_resources(console=self._console,
                                                               namespace=self._namespace,
                                                               platform=self._setup.platform,
                                                               filter=self._cr_details["name"])
        
        if len(resource_type_dict["network_policy"]) == 0:
            self._logger.info("There exists no network policy managed by the operator")
            return False
        
        # Create folder for network policies if it does not exist
        self._networkwork_policy_save_location = os.path.join(os.getcwd(), "CASUpgrade", self._namespace, "NetworkPolicies")
        if not os.path.exists(self._networkwork_policy_save_location):
            os.makedirs(self._networkwork_policy_save_location)

        if not os.path.exists(self._networkwork_policy_ingress_save_location):
            os.makedirs(self._networkwork_policy_ingress_save_location)

        if not os.path.exists(self._networkwork_policy_egress_save_location):
            os.makedirs(self._networkwork_policy_egress_save_location)

        try:
            self._logger.info("Starting Network Policy Information Collection")
            for network_policy in resource_type_dict["network_policy"]:
                self._logger.info(f"Collecting network policy {network_policy}")
                if "ingress" in network_policy:
                    path = os.path.join(
                    f"{self._networkwork_policy_ingress_save_location}",
                    f"{network_policy}.yaml")
                else:
                    path = os.path.join(
                        f"{self._networkwork_policy_egress_save_location}",
                        f"{network_policy}.yaml")
                if os.path.isfile(path):
                    self._logger.info("Network Policy file already exists.")
                else:
                    network_policy_response = self._kube.describe_network_policy(network_policy, self._namespace)
                    write_yaml_to_file(network_policy_response, path)
            self.clean_networkpolicies(self._networkwork_policy_ingress_save_location)
            self.clean_networkpolicies(self._networkwork_policy_egress_save_location)

            self._logger.info("Network Policies have been downloaded")
            self._updates_list.append("Network Policies downloaded")
            return True
                
        except Exception as e:
            self._logger.info("Unable to retrieve network policies, caught %s Skipping...", e)

    def update_network_policy(self, progress):
        resource_type_dict = self._kube.resource_type_dict
        try:
            progress.log()
            progress.log(Panel.fit("Starting Network Policy Patch", style="cyan"))
            progress.log()
            self._logger.info(f"Starting Network Policy Patch")

            for network_policy in resource_type_dict["network_policy"]:
                self._kube.remove_network_policy_owner_reference(progress= progress,network_policy_name= network_policy,namespace= self._namespace)
            if resource_type_dict["network_policy"] :
                progress.log(Panel.fit("Network Policy Information Collection Completed", style="bold green"))
                progress.log(Panel.fit("Owner references for existing Network policy has been removed", style="bold green"))
                progress.log()
                self._logger.info(f"All network policy information is collected and owner references for existing network policies have been removed.")
            else:
                progress.log(Panel.fit("There exists no network policy managed by the IBM Content Assistant Operator", style="bold green"))
                progress.log()
                self._logger.info(f"There exists no network policy managed by the IBM Content Assistant Operator")
        except Exception as e:
            self._logger.info("Unable to retrieve network policies, caught %s Skipping...", e)
            self._logger.info(f"An error occured while retrieving the network policies: {e}")

    def remove_custom_ssl_secrets(self, progress):
        resource_type_dict = self._kube.resource_type_dict
        try:

            cr_name = self._cr_details["name"]

            secrets = [
                f"{cr_name}-cas-custom-ssl-secret",
            ]

            if 'secret' in resource_type_dict:
                progress.log()
                progress.log(Panel.fit("Starting Custom SSL Certificates Patch", style="cyan"))
                progress.log()
                self._logger.info(f"Patching custom ssl certificates")
                for secret in secrets:
                    if secret in resource_type_dict["secret"]:
                        self._kube.delete_secret(namespace=self._namespace, name=secret )
                        progress.log(f"Secret '{secret}' patched successfully.")
                        progress.log()
                        self._logger.info(f"Secret '{secret}' patched successfully.")
                
                progress.log(Panel.fit("Custom SSL Certificates Patch Completed", style="bold green"))
                progress.log()
                self._logger.info(f"Completed patching of custom ssl certificates")
        
        except Exception as e:
            self._logger.info(f"Unable to retrieve secrets: {e}")
        


    # Function to update certain CR parameters , used in the upgrade script
    def update_cr_values(self):
        """
        Updates the current CASCluster Custom Resource values based on the full CR template.

        Applies the new release label, appVersion, removes pinned image tags so the operator
        uses its built-in digest defaults, refreshes resource requests/limits, strips the
        live-cluster status field, and sets the license model.

        Returns:
            tuple: (updated_cr_details, list_of_updates) or ({},) on fatal error.
        """
        try:
            cr_details = self._current_cr.copy()
            fc_template_cr = self.required_file_paths["ibm_content_assistant_full_cr.yaml"]
            update_list = []

            try:
                with open(fc_template_cr, 'r') as yaml_file:
                    fc_template_cr_details = yaml.safe_load(yaml_file)
            except Exception:
                self._logger.exception('Unable to load Full Custom Resource Template')
                return {}

            # Update release label
            if is_key_present(dictionary=cr_details, key="release"):
                release = fc_template_cr_details["metadata"]["labels"]["release"]
                cr_details["metadata"]["labels"]["release"] = release
                update_list.append(f"Updated release label to {release}")

            # Update appVersion
            if is_key_present(dictionary=cr_details, key="appVersion"):
                app_version = fc_template_cr_details["spec"]["appVersion"]
                cr_details["spec"]["appVersion"] = app_version
                update_list.append(f"Updated appVersion to {app_version}")

            # Remove image tags so the operator falls back to its built-in digest defaults
            if is_key_present(cr_details, "tag"):
                for nested_structure, path, key in find_keys_and_structures(dictionary=cr_details, key="tag"):
                    try:
                        delete_key_by_path(cr_details, path, key, logger=self._logger)
                    except KeyError as e:
                        self._logger.info(e)
                update_list.append("Removed image tags (operator digest defaults will be used)")

            # Update resource requests and limits to match new release template values
            if is_key_present(cr_details, key="requests") and is_key_present(cr_details, key="limits"):
                update_list.append("Updated component resource requests and limits")
                for nested_structure, path, _key in find_keys_and_structures(dictionary=cr_details, key="requests"):
                    try:
                        update_value_by_path(dictionary1=cr_details, path=path,
                                             dictionary2=fc_template_cr_details,
                                             requests=True, logger=self._logger)
                    except (KeyError, Exception) as e:
                        self._logger.info(e)
                for nested_structure, path, _key in find_keys_and_structures(dictionary=cr_details, key="limits"):
                    try:
                        update_value_by_path(dictionary1=cr_details, path=path,
                                             dictionary2=fc_template_cr_details,
                                             limits=True, logger=self._logger)
                    except KeyError as e:
                        self._logger.info(e)

            # Remove live-cluster status field — must not be re-applied
            if is_key_present(cr_details, key="status"):
                cr_details.pop("status")
                update_list.append("Removed status field")

            # Update license model (Content Assistant field: sc_cas_license_type)
            if self._selected_license:
                if "shared_configuration" in cr_details.get("spec", {}):
                    cr_details["spec"]["shared_configuration"]["sc_cas_license_type"] = self._selected_license
                    update_list.append(f"Updated license model to {self._selected_license}")
                else:
                    self._logger.warning("shared_configuration not found in CR, cannot update license model")

            return cr_details, update_list

        except Exception:
            self._logger.exception("Exception while updating Custom Resource fields and sections")
            return {}

    # Function to prepare the upgrade CR and save it in the .tmp folder
    def prepare_upgrade_cr(self):
        """
        This function prepares for an upgrade of the Custom Resource (CR) by retrieving the current CR,
        backing up the existing CR folder, and generating an updated CR file.

        Parameters:
        self (object): An instance of the class containing this method.

        Returns:
        None
        """

        self._logger.info(f"Preparing for upgrade")
        self._current_cr = self._kube.get_deployment_cr(
            namespace=self._namespace, logger=self._logger)
        if not self._current_cr:
            self._logger.info(
                "Error will retrieving Custom Resource File. This Means either the namespace entered was incorrect or a custom resource file does not exist\n"
                "Run the script without the deployment flag if no Custom Resource file exists\n")
            print(Panel.fit("Unable to retrieve Content Assistant Custom Resource file.\n"
                            "Please check your namespace or CR type \"CASCluster\"", style="bold red"))
            print()
            exit(1)

        cr_details = self._kube.cr_details
        self._cr_details = cr_details

        # Backup existing Custom Resource folder
        if os.path.exists(self._download_location):
            self._logger.info("Backup existing Upgrade folder")
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            zip_folder(os.path.join(os.getcwd(), "backups", f"CASUpgrade_{self._namespace}_{dt_string}"),
                       self._download_location)
            shutil.rmtree(self._download_location)
            os.makedirs(self._download_location)
            os.makedirs(self._cr_template_save_location)
        else:
            self._logger.info(f"Creating CASUpgrade/{self._namespace} folder")
            os.makedirs(self._download_location)
            os.makedirs(self._cr_template_save_location)

        # Get Version info
        current_version = cr_details["version"]
        current_version = current_version.replace(".", "")
        upgrade_version = self._version_details["version"]
        upgrade_version = upgrade_version.replace(".", "")

        # Create the file paths for the current and updated CR
        self._current_cr_template_save_location = os.path.join(self._cr_template_save_location,
                                                               f"cas_deployed_cr.yaml")
        self._updated_cr_template_save_location = os.path.join(self._cr_template_save_location,
                                                               f"cas_{upgrade_version}_cr.yaml")

        # Writing the current cr to a file
        self._logger.info(f"Writing the current cr to {self._current_cr_template_save_location}")
        write_yaml_to_file(self._current_cr, self._current_cr_template_save_location)

        # Generate the updated CR
        self._logger.info(f"Generating the updated cr at: {self._updated_cr_template_save_location}")
        updated_cr, update_list = self.update_cr_values()

        self._updates_list = update_list

        # writing the data to a file
        write_yaml_to_file(updated_cr, self._updated_cr_template_save_location)

        # Generate metrics YAMLs for deployed components
        self._generate_metrics_yamls(updated_cr)

    def _generate_metrics_yamls(self, cr_data):
        """
        Generate the ICA GenAI usage metering metrics YAML file.

        Generates the IBMServiceMeterDefinition for the GenAI deployment and writes
        it to the CASUpgrade/Metrics folder for application during the upgrade process.

        Args:
            cr_data: The Custom Resource dictionary (unused, kept for signature consistency)
        """
        try:
            self._logger.info("Generating ICA GenAI usage metering metrics")

            # Create Metrics folder if it doesn't exist
            if not os.path.exists(self._metrics_save_location):
                os.makedirs(self._metrics_save_location)
                self._logger.info(f"Created metrics folder: {self._metrics_save_location}")

            # GENAI metrics are always generated for ICA deployments
            deployment_properties = {'GENAI': True}

            # Initialize the metrics generator
            metrics_generator = GenerateMetrics(
                deployment_properties=deployment_properties,
                namespace=self._namespace,
                logger=self._logger
            )

            # Override the generated folder to use CASUpgrade/Metrics instead of generatedFiles
            metrics_generator._generated_folder = Path(self._metrics_save_location)

            # Generate the GENAI metrics
            success = metrics_generator.generate_component_metrics("GENAI")
            
            if success:
                self._logger.info(f"✓ Successfully generated metrics YAMLs in CASUpgrade/{self._namespace}/Metrics folder")
                print()
                print(Panel.fit(
                    "[bold green]✓ Metrics YAMLs Generated[/bold green]\n\n"
                    f"Usage metering metrics have been generated in:\n"
                    f"[cyan]{self._metrics_save_location}[/cyan]\n\n"
                    "These metrics will be applied during the upgrade process.",
                    border_style="green"
                ))
            else:
                self._logger.warning("⚠ Some metrics failed to generate, check logs for details")
                print()
                print(Panel.fit(
                    "[bold yellow]⚠ Metrics Generation Warning[/bold yellow]\n\n"
                    "Some metrics YAMLs may not have been generated.\n"
                    "Check the logs for details.",
                    border_style="yellow"
                ))
                
        except Exception as e:
            self._logger.error(f"Error generating metrics YAMLs: {str(e)}")
            print()
            print(Panel.fit(
                f"[bold red]✗ Metrics Generation Error[/bold red]\n\n"
                f"Failed to generate metrics YAMLs: {str(e)}\n\n"
                "The upgrade can continue, but metrics may need to be generated manually.",
                border_style="red"
            ))

    # logic to scale down and wait for pods replica count to be zero
    # additional logic is there to scale up the pods if required which can be done using scale="up"
    def scale_pods(self, scale="down", progress=None):
        """
        Scale down deployments before upgrade.
        
        Note: This method is called from apply_upgraded_cr() which handles the UI display.
        No UI output is needed here as it's part of the larger upgrade flow.
        """
        try:
            upgrade_version = self._version_details["version"]
            
            self._logger.info(f"Scaling down IBM Content Assistant Deployments")

            cr_name = self._cr_details["name"]
            deployments = self._kube.get_deployments_by_owner_reference(
                namespace=self._namespace,
                owner_reference_name=cr_name)

            self._logger.info(f"Scaling down current IBM Content Assistant Operator pod before upgrading")

            # Scale down older operator pod before upgrading (if deployment info is available)
            if "deployment" in self._operator_details and self._operator_details["deployment"]:
                operator_deployment = self._operator_details["deployment"]
                self._kube.scale_operator_deployment(namespace=self._namespace,
                                                     deployment_name=operator_deployment,
                                                     scale="down")
                self._logger.info(f"Successfully scaled down operator deployment: {operator_deployment}")
            else:
                self._logger.warning("Operator deployment information not available, skipping scale down")

        except KeyError as e:
            self._logger.error(f"Missing required key in operator details: {e}")
            raise
        except Exception as e:
            self._logger.error(f"Error in scaling down pods function: {e}")
            raise

    # Ask if the CR should be updated, if user does not want to update CR we will just update the Operators
    # IF CR is to be updated then we will scale pods down , apply the latest CR and then upgrade the operator
    def apply_upgraded_cr(self, progress=None):
        """
        Apply the upgraded Custom Resource with table-based progress tracking.

        Applies the upgraded CR to the cluster and then applies any generated
        metrics YAMLs.  Uses a live-updating table for status feedback.

        Args:
            progress: Optional progress tracker (not used, kept for compatibility)
        """
        from rich.live import Live
        from rich.table import Table
        from rich.text import Text
        from threading import Lock

        self._logger.info("Applying Upgraded Custom Resource")

        # Only the two real operations are tracked
        application_status = {
            "Applying Custom Resource": {"status": "⏳ Pending", "details": ""},
        }
        status_lock = Lock()

        def create_status_table():
            table = Table(
                title="📦 Applying Upgraded Custom Resource",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
                title_style="bold cyan"
            )
            table.add_column("Application Phase", style="cyan", width=35)
            table.add_column("Status", style="white", width=20)
            table.add_column("Details", style="white", width=40)

            for phase, info in application_status.items():
                status = info["status"]
                details = info["details"]

                if "✓" in status:
                    style = "green"
                elif "🔄" in status:
                    style = "yellow"
                elif "✗" in status:
                    style = "red"
                else:
                    style = "dim white"

                table.add_row(
                    phase,
                    Text(status, style=style),
                    Text(details, style="dim white" if not details else "white")
                )
            return table

        error_occurred = False
        error_message = ""

        print()
        with Live(create_status_table(), console=self._console, refresh_per_second=4) as live:
            # Apply Custom Resource
            with status_lock:
                application_status["Applying Custom Resource"]["status"] = "🔄 Applying..."
                application_status["Applying Custom Resource"]["details"] = "Applying Custom Resource to cluster"
                live.update(create_status_table())

            cr_applied = self._kube.apply_cluster_resource_files(
                resource_file=self._updated_cr_template_save_location,
                resource_type="Custom Resource",
                namespace=self._namespace
            )

            if cr_applied:
                with status_lock:
                    application_status["Applying Custom Resource"]["status"] = "✓ Complete"
                    application_status["Applying Custom Resource"]["details"] = "Custom Resource applied successfully"
                    live.update(create_status_table())
                self._logger.info("Upgraded Custom Resource applied successfully")
            else:
                error_message = "Failed to apply Custom Resource"
                with status_lock:
                    application_status["Applying Custom Resource"]["status"] = "✗ Error"
                    application_status["Applying Custom Resource"]["details"] = f"Error: {error_message}"
                    live.update(create_status_table())
                error_occurred = True
                self._logger.error(f"Error occurred while applying the upgraded Custom Resource: {error_message}")

        if error_occurred:
            print()
            print(Text(f"✗ {error_message}", style="bold red"))
            exit(1)

        print()
        print(Text("✓ Upgraded Custom Resource applied successfully", style="bold green"))

        # Apply metrics YAMLs if they exist
        self._apply_metrics_yamls()

    def _apply_metrics_yamls(self):
        """
        Apply usage metering metrics YAML files with table-based progress tracking.
        
        This method checks for metrics files in the CASUpgrade/<namespace>/Metrics folder and applies
        them to the cluster with a live-updating table similar to the mustgather UI.
        """
        from rich.live import Live
        from rich.table import Table
        from rich.text import Text
        from threading import Lock
        
        try:
            # Check if metrics folder exists and has files
            if not os.path.exists(self._metrics_save_location):
                self._logger.info("No metrics folder found, skipping metrics deployment")
                return
            
            metrics_files = [f for f in os.listdir(self._metrics_save_location)
                           if f.endswith('.yaml') or f.endswith('.yml')]
            
            if not metrics_files:
                self._logger.info("No metrics files found, skipping metrics deployment")
                return
            
            self._logger.info(f"Applying {len(metrics_files)} metrics YAML(s)")
            
            # Initialize status tracking for each metrics file
            metrics_status = {}
            for metrics_file in metrics_files:
                # Extract component name for display
                component_name = metrics_file.replace('ccx-', '').replace('-metrics.yaml', '').upper()
                metrics_status[component_name] = {"status": "⏳ Pending", "details": ""}
            
            status_lock = Lock()
            
            def create_metrics_table():
                """Create a fresh status table with current metrics application status"""
                table = Table(
                    title="📊 Applying Usage Metering Metrics",
                    show_header=True,
                    header_style="bold cyan",
                    border_style="cyan",
                    title_style="bold cyan"
                )
                table.add_column("Metrics Component", style="cyan", width=25)
                table.add_column("Status", style="white", width=20)
                table.add_column("Details", style="white", width=50)
                
                for component, info in metrics_status.items():
                    status = info["status"]
                    details = info["details"]
                    
                    if "Complete" in status or "✓" in status:
                        style = "green"
                    elif "Applying" in status or "🔄" in status:
                        style = "yellow"
                    elif "Error" in status or "✗" in status:
                        style = "red"
                    else:
                        style = "dim white"
                    
                    table.add_row(
                        component,
                        Text(status, style=style),
                        Text(details, style="dim white" if not details else "white")
                    )
                return table
            
            # Start live display
            print()
            with Live(create_metrics_table(), console=self._console, refresh_per_second=4) as live:
                applied_count = 0
                failed_count = 0
                
                for metrics_file in metrics_files:
                    metrics_path = os.path.join(self._metrics_save_location, metrics_file)
                    component_name = metrics_file.replace('ccx-', '').replace('-metrics.yaml', '').upper()
                    
                    # Update status to applying
                    with status_lock:
                        metrics_status[component_name]["status"] = "🔄 Applying..."
                        metrics_status[component_name]["details"] = f"Applying {metrics_file}"
                        live.update(create_metrics_table())
                    
                    self._logger.info(f"Applying metrics file: {metrics_file}")
                    
                    try:
                        success = self._kube.apply_cluster_resource_files(
                            resource_file=metrics_path,
                            resource_type="IBMServiceMeterDefinition",
                            namespace=self._namespace
                        )
                        
                        if success:
                            applied_count += 1
                            with status_lock:
                                metrics_status[component_name]["status"] = "✓ Complete"
                                metrics_status[component_name]["details"] = "Metrics applied successfully"
                                live.update(create_metrics_table())
                            self._logger.info(f"✓ Successfully applied {metrics_file}")
                        else:
                            failed_count += 1
                            with status_lock:
                                metrics_status[component_name]["status"] = "✗ Failed"
                                metrics_status[component_name]["details"] = "Application returned false"
                                live.update(create_metrics_table())
                            self._logger.warning(f"✗ Failed to apply {metrics_file}")
                            
                    except Exception as e:
                        failed_count += 1
                        error_msg = str(e)[:45] + "..." if len(str(e)) > 45 else str(e)
                        with status_lock:
                            metrics_status[component_name]["status"] = "✗ Error"
                            metrics_status[component_name]["details"] = error_msg
                            live.update(create_metrics_table())
                        self._logger.error(f"Error applying {metrics_file}: {str(e)}")
            
            # Summary message
            print()
            if failed_count == 0:
                print(Text(f"✓ All {len(metrics_files)} metrics applied successfully", style="bold green"))
                self._logger.info(f"✓ All {len(metrics_files)} metrics applied successfully")
            else:
                print(Text(f"⚠ Applied {applied_count}/{len(metrics_files)} metrics ({failed_count} failed)",
                          style="bold yellow"))
                self._logger.warning(f"⚠ Applied {applied_count}/{len(metrics_files)} metrics ({failed_count} failed)")
                
        except Exception as e:
            error_msg = f"Error during metrics deployment: {str(e)}"
            print()
            print(Text(f"✗ {error_msg}", style="bold red"))
            self._logger.error(error_msg)

    # Function to display the post upgrade steps
    # Jason to fill this up as part of the upgrade steps
    def post_upgrade_steps(self):
        print("Here are the post upgrade steps to follow\n")
        print("TBA")
