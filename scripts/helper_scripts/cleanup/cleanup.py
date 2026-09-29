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
import json
import requests
import subprocess
import time
from click import style
from rich.panel import Panel
from rich.text import Text

requests.packages.urllib3.disable_warnings()
from ..utilities import kubernetes_utilites as k


# CLass that contains functions to delete the CR as well delete the Operator
class CleanDeployment:

    def __init__(self, console, deployment_prerequisites=None, logger=None, silent=False):
        self._deployment_prerequisites = deployment_prerequisites
        self._namespace = deployment_prerequisites.namespace
        self._logger = logger
        self._console = console
        self._clean_deployment = False
        self._silent = silent
        self._kube = k.KubernetesUtilities(logger)
        self._apps_v1_api = self._kube.apps_v1
        self._core_v1_api = self._kube.core_v1
        self._custom_api = self._kube.custom_api
        self._operator_details = {}
        self._cr_details = {}
        self._cr_name = "casdeploy"

    def collect_cr_details(self):
        self._logger.info(f"Collecting CR details")
        try:
            cr_list = self._custom_api.list_namespaced_custom_object(
                group="cas.ibm.com",
                version="v1",
                namespace=self._namespace,
                plural="casclusters"
            )
            items = cr_list.get("items", [])
            cr_details = items[0] if items else {}
        except Exception as e:
            self._logger.info(f"No CASCluster CR found in '{self._namespace}': {e}")
            cr_details = {}

        self._cr_details = cr_details

        if not cr_details:
            return {}, {}

        self._cr_name = cr_details.get("metadata", {}).get("name", "casdeploy")
        version = cr_details.get("spec", {}).get("appVersion", "1.0.0")

        self.resource_type_dict = self._kube.list_namespace_resources(console=self._console,
                                                                      namespace=self._namespace,
                                                                      filter=self._cr_name)
        deployment_details_dict = {
            "Namespace": self._namespace,
            "Name": self._cr_name,
            "Version": version
        }

        return deployment_details_dict, self.resource_type_dict

    def delete_CR(self, task1, progress, cr_type="Content Assistant", group="cas.ibm.com",
                  version="v1", plural="casclusters", cr_name=None):
        """
        Delete a Custom Resource (CR) and its associated resources.

        Args:
            task1: Progress task ID
            progress: Progress instance for logging
            cr_type: Type of CR (e.g., "Content Assistant")
            group: API group (e.g., "cas.ibm.com")
            version: API version (e.g., "v1")
            plural: Resource plural (e.g., "casclusters")
            cr_name: Name of the CR (defaults to self._cr_name)
        """
        SLEEP_TIMER = 5
        cr_name = cr_name or self._cr_name
        
        # Attempt to list the CR in the specific namespace
        progress.log(f"Starting IBM Content Assistant {cr_type} Deployment Cleanup")
        progress.log()
        self._logger.info(f"Starting IBM Content Assistant {cr_type} Deployment Cleanup")
        progress.log("Cleaning up namespace: " + self._namespace)
        self._logger.info(f"Cleaning up namespace: {self._namespace}")

        try:
            self._custom_api.delete_namespaced_custom_object(
                group=group,
                version=version,
                namespace=self._namespace,
                plural=plural,
                name=cr_name
            )
        except Exception as e:
            if getattr(e, "status", None) == 404:
                self._logger.info(f"{cr_type} CR '{cr_name}' is already deleted")
            else:
                self._logger.error(f"Error deleting {cr_type} CR: {e}")
                progress.log(f"[red]Error deleting {cr_type} CR: {e}[/red]")
                raise

        progress.log()
        progress.log(f"Deleting {cr_type} CR...")
        self._logger.info(f"Deleting {cr_type} CR")
        time.sleep(SLEEP_TIMER)
        progress.advance(task1)

        progress.log()
        progress.log("Waiting for pods to gracefully shutdown...")
        self._logger.info(f"Waiting for pods to gracefully shutdown")

        # TODO: Check if the pods exists using labels query
        # TODO: Check logic if pods are sticking around
        # TODO: Update with CR name as owner

        try:
            deployments = self._kube.get_deployments_by_owner_reference(namespace=self._namespace,
                                                                        owner_reference_name=cr_name)
            if deployments:
                pods_to_delete = []
                for deployment in deployments:
                    pods = self._kube.get_pods_for_deployment(namespace=self._namespace,
                                                              deployment_name=deployment.metadata.name)
                    if pods:
                        for pod in pods:
                            pods_to_delete.append(pod.metadata.name)
            else:
                pods_to_delete = []

            retries = 0
            while retries < 20:
                pods_present = []
                pods = self._core_v1_api.list_namespaced_pod(self._namespace)
                for pod in pods.items:
                    pods_present.append(pod.metadata.name)
                any_pod_still_present = any(item in pods_present for item in pods_to_delete)
                if any_pod_still_present:
                    retries = retries + 1
                    time.sleep(SLEEP_TIMER)
                else:
                    break
            if retries == 20:
                msg = (
                    f"Timeout waiting for pods to terminate in namespace '{self._namespace}'. "
                    f"Check pod status with: kubectl get pods -n {self._namespace}"
                )
                self._logger.warning(msg)
                raise Exception(msg)
        except Exception as e:
            self._logger.error(f"Unexpected error while waiting for pods to terminate in namespace '{self._namespace}': {e}")
            progress.log(f"[red]Error waiting for pod termination: {e}[/red]")
            raise

        progress.log()
        progress.log(Panel.fit(Text("All resources have been deleted successfully..."), style="bold green"))
        self._logger.info(f"All resources have been deleted successfully")
        progress.advance(task1)

    def collect_operator_details(self):
        # Collect details for both the Content Assistant operator and Usage Metering operator.
        # Returns the Content Assistant operator details (primary) so the existing caller contract
        # is preserved, but also stores usage-metering details for use in delete_operator().

        # Try Kubernetes deployment lookup first
        operator_deployment = "ibm-content-assistant-operator"
        self._logger.info(f"Getting {operator_deployment} details")
        operator_details = self._kube.get_operator_details(self._namespace, operator_deployment)

        # Fall back to Helm release check if deployment is not found
        if not operator_details:
            self._logger.info(f"Deployment not found, checking Helm releases in {self._namespace}")
            try:
                result = subprocess.run(
                    ["helm", "list", "-n", self._namespace, "-o", "json"],
                    capture_output=True, text=True, check=True
                )
                releases = json.loads(result.stdout)
                release_names = [r.get("name") for r in releases]
                if "ibm-content-assistant-operator" not in release_names:
                    self._logger.info("No Content Assistant operator found via deployment or Helm")
                    return {}
                # Build a minimal operator_details dict so delete_operator knows to use helm uninstall
                cas_release = next((r for r in releases if r.get("name") == "ibm-content-assistant-operator"), {})
                operator_details = {
                    "deployment": "ibm-content-assistant-operator",
                    "type": "HELM",
                    "helm_release": "ibm-content-assistant-operator",
                    "release": cas_release.get("chart", "ibm-content-assistant-operator"),
                    "version": cas_release.get("app_version", "unknown"),
                    "image": "",
                    "registry": "",
                    "namespace": self._namespace,
                }
                self._logger.info("Found Content Assistant operator via Helm release")
            except Exception as e:
                self._logger.info(f"Error checking Helm releases: {e}")
                return {}

        self._operator_details = operator_details

        # Also collect usage-metering operator details
        um_deployment = "ibm-usage-metering-operator"
        self._logger.info(f"Getting {um_deployment} details")
        um_details = self._kube.get_operator_details(self._namespace, um_deployment)

        # Fall back to Helm for usage-metering too
        if not um_details:
            try:
                result = subprocess.run(
                    ["helm", "list", "-n", self._namespace, "-o", "json"],
                    capture_output=True, text=True, check=True
                )
                releases = json.loads(result.stdout)
                release_names = [r.get("name") for r in releases]
                if "ibm-usage-metering" in release_names:
                    um_details = {
                        "deployment": "ibm-usage-metering-operator",
                        "type": "HELM",
                        "helm_release": "ibm-usage-metering",
                    }
                    self._logger.info("Found Usage Metering operator via Helm release")
            except Exception as e:
                self._logger.info(f"Error checking Helm releases for usage-metering: {e}")

        self._usage_metering_details = um_details or {}

        return operator_details

    # This function takes care of the deletion of operator after the CR and resources are deleted
    def delete_operator(self, task1, progress, delete_um_operator: bool = False, task_um=None):
        SLEEP_TIMER = 5

        op_details = self._operator_details
        um_details = getattr(self, "_usage_metering_details", {})

        # ── PART 1: Delete Main Content Assistant Operator ───────────────────
        if op_details:
            if hasattr(progress, "start"):
                progress.start(task1)
            if op_details.get("type") == "OLM":
                # ── OLM path ──────────────────────────────────────────────────
                subscription_name = op_details.get("subscription")
                installed_csv     = op_details.get("installedCSV")
                operator_group    = op_details.get("operatorGroup")
                catalog_source    = op_details.get("catalogSource")
                provided_apis     = op_details.get("providedAPIs")
                if isinstance(provided_apis, str):
                    provided_apis = [api.strip() for api in provided_apis.split(",")]

                progress.log("Starting IBM Content Assistant Operator OLM Uninstallation")
                progress.log()
                self._logger.info("Starting IBM Content Assistant Operator OLM uninstallation")
                time.sleep(SLEEP_TIMER)

                progress.log()
                progress.log("Deleting Subscription...")
                self._logger.info("Deleting Subscription")
                if subscription_name:
                    self._kube.delete_subscription(namespace=self._namespace, name=subscription_name)
                else:
                    progress.log(Panel.fit("Subscription not found", style="bold red"))
                    self._logger.info("Subscription not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log("Deleting CSV...")
                self._logger.info("Deleting CSV")
                if installed_csv:
                    self._kube.delete_clusterserviceversion(csv_name=installed_csv, namespace=self._namespace)
                else:
                    progress.log(Panel.fit("CSV not found", style="bold red"))
                    self._logger.info("CSV not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                if provided_apis and len(provided_apis) > 1:
                    progress.log()
                    progress.log("Updating Operator Group to remove the Content Assistant Operator API...")
                    self._logger.info("Updating Operator Group to remove the Content Assistant Operator API")
                    self._kube.update_operator_group(namespace=self._namespace,
                                                     operator_group=operator_group,
                                                     provided_apis=provided_apis)
                else:
                    progress.log()
                    progress.log("Deleting Operator Group...")
                    self._logger.info("Deleting Operator Group")
                    if operator_group:
                        self._kube.delete_operator_group(namespace=self._namespace, name=operator_group)
                    else:
                        progress.log(Panel.fit("Operator Group not found", style="bold red"))
                        self._logger.info("Operator Group not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                if op_details.get("catalogType", "").lower() == "private":
                    progress.log()
                    progress.log("Deleting Catalog Source...")
                    self._logger.info("Deleting Catalog Source")
                    self._kube.delete_catalog_source(namespace=self._namespace, name=catalog_source)
                    time.sleep(SLEEP_TIMER)
                else:
                    progress.log()
                    progress.log("Skipping Catalog Source deletion (global scope)...")
                    self._logger.info("Skipping Catalog Source deletion (global scope)")

                progress.log()
                progress.log(Panel.fit("Uninstalling IBM Content Assistant Operator completed!", style="bold green"))
                self._logger.info("IBM Content Assistant Operator OLM uninstallation completed!")
                progress.advance(task1)

            elif op_details.get("type") == "HELM":
                # ── Helm path ─────────────────────────────────────────────────
                progress.log("Starting IBM Content Assistant Helm Uninstallation")
                progress.log()
                self._logger.info("Starting IBM Content Assistant Helm uninstallation")
                time.sleep(SLEEP_TIMER)

                cas_release = op_details.get("helm_release", op_details.get("deployment", "ibm-content-assistant-operator"))
                progress.log()
                progress.log(f"Running: helm uninstall {cas_release}...")
                self._logger.info(f"Uninstalling Helm release: {cas_release}")

                result = subprocess.run(
                    ["helm", "uninstall", cas_release, "-n", self._namespace],
                    capture_output=True, text=True, check=False
                )
                if result.returncode != 0:
                    self._logger.warning(f"Normal uninstall failed, retrying with --no-hooks: {result.stderr}")
                    result = subprocess.run(
                        ["helm", "uninstall", cas_release, "-n", self._namespace,
                         "--no-hooks", "--wait=false"],
                        capture_output=True, text=True, check=False
                    )
                if result.returncode != 0:
                    progress.log(Panel.fit(f"Failed to uninstall {cas_release}: {result.stderr}", style="bold red"))
                    self._logger.error(f"helm uninstall failed for {cas_release}: {result.stderr}")
                else:
                    progress.log(f"[green]✓[/green] Helm release {cas_release} uninstalled")
                    self._logger.info(f"Helm release {cas_release} uninstalled successfully")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log(Panel.fit("Uninstalling IBM Content Assistant Operator completed!", style="bold green"))
                self._logger.info("IBM Content Assistant Helm uninstallation completed!")
                progress.advance(task1)

            else:
                # ── YAML path ─────────────────────────────────────────────────
                role            = op_details.get("role") or None
                rolebinding     = op_details.get("rolebinding") or None
                service_account = op_details.get("service_account") or None

                progress.log("Starting IBM Content Assistant Operator Uninstallation")
                progress.log()
                self._logger.info("Starting IBM Content Assistant Operator uninstallation")
                time.sleep(SLEEP_TIMER)

                progress.log()
                progress.log("Deleting Operator Deployment...")
                self._logger.info("Deleting Operator Deployment")
                self._kube.delete_operator_deployment(
                    namespace=self._namespace,
                    name=op_details.get("deployment", "ibm-content-assistant-operator")
                )
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log("Deleting Operator RoleBinding...")
                self._logger.info("Deleting Operator RoleBinding")
                if rolebinding:
                    self._kube.delete_role_binding(namespace=self._namespace, name=rolebinding)
                else:
                    progress.log(Panel.fit("RoleBinding not found", style="bold red"))
                    self._logger.info("RoleBinding not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log("Deleting Operator Role...")
                self._logger.info("Deleting Operator Role")
                if role:
                    self._kube.delete_role(namespace=self._namespace, name=role)
                else:
                    progress.log(Panel.fit("Role not found", style="bold red"))
                    self._logger.info("Role not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log("Deleting Operator Service Account...")
                self._logger.info("Deleting Operator Service Account")
                if service_account:
                    self._kube.delete_service_account(namespace=self._namespace, name=service_account)
                else:
                    progress.log(Panel.fit("Service Account not found", style="bold red"))
                    self._logger.info("Service Account not found")
                time.sleep(SLEEP_TIMER)
                progress.advance(task1)

                progress.log()
                progress.log(Panel.fit("Uninstalling IBM Content Assistant Operator completed!", style="bold green"))
                self._logger.info("IBM Content Assistant Operator uninstallation completed!")
                progress.advance(task1)

        # ── PART 2: Delete Usage Metering Operator (if requested) ────────────
        if um_details and delete_um_operator:
            if hasattr(progress, "start"):
                progress.start(task_um)
            um_type = um_details.get("type", "YAML")
            progress.log()
            progress.log(f"Starting Usage Metering Operator Uninstallation (type: {um_type})...")
            self._logger.info(f"Starting Usage Metering Operator uninstallation of type: {um_type}")
            time.sleep(SLEEP_TIMER)

            # 1. First delete IBMUsageMetering Custom Resources (CRs)
            progress.log("Deleting Usage Metering Custom Resources...")
            try:
                um_cr_list = self._kube._custom_api.list_namespaced_custom_object(
                    group="operator.ibm.com", version="v1",
                    namespace=self._namespace, plural="ibmusagemeterings"
                ).get("items", [])
                for um_cr in um_cr_list:
                    cr_name = um_cr["metadata"]["name"]
                    self._kube._custom_api.delete_namespaced_custom_object(
                        group="operator.ibm.com", version="v1",
                        namespace=self._namespace, plural="ibmusagemeterings",
                        name=cr_name
                    )
                    self._logger.info(f"Deleted IBMUsageMetering CR: {cr_name}")
            except Exception as _e:
                self._logger.info(f"IBMUsageMetering CR not found or already deleted: {_e}")
            if task_um is not None:
                progress.advance(task_um)

            # 2. Type-specific Operator Cleanup
            if um_type == "OLM":
                # Discover Usage Metering OLM Subscription and CSV
                um_subscription = None
                um_csv = None
                try:
                    subscriptions = self._custom_api.list_namespaced_custom_object(
                        group="operators.coreos.com", version="v1alpha1",
                        namespace=self._namespace, plural="subscriptions"
                    ).get("items", [])
                    for sub in subscriptions:
                        sub_name = sub.get("metadata", {}).get("name", "")
                        if "ibm-usage-metering" in sub_name or "ibm-usage-metering" in sub.get("spec", {}).get("name", ""):
                            um_subscription = sub_name
                            um_csv = sub.get("status", {}).get("installedCSV")
                            break
                except Exception as e:
                    self._logger.info(f"Error searching OLM subscriptions for Usage Metering: {e}")

                if not um_csv:
                    try:
                        csvs = self._custom_api.list_namespaced_custom_object(
                            group="operators.coreos.com", version="v1alpha1",
                            namespace=self._namespace, plural="clusterserviceversions"
                        ).get("items", [])
                        for csv in csvs:
                            csv_name = csv.get("metadata", {}).get("name", "")
                            if csv_name.startswith("ibm-usage-metering"):
                                um_csv = csv_name
                                break
                    except Exception as e:
                        self._logger.info(f"Error listing ClusterServiceVersions for Usage Metering: {e}")

                # Delete OLM Subscription
                if um_subscription:
                    progress.log(f"Deleting Usage Metering Subscription: {um_subscription}...")
                    self._kube.delete_subscription(namespace=self._namespace, name=um_subscription)
                else:
                    progress.log("Usage Metering OLM Subscription not found")
                time.sleep(SLEEP_TIMER)
                if task_um is not None:
                    progress.advance(task_um)

                # Delete OLM CSV
                if um_csv:
                    progress.log(f"Deleting Usage Metering ClusterServiceVersion: {um_csv}...")
                    self._kube.delete_clusterserviceversion(csv_name=um_csv, namespace=self._namespace)
                else:
                    progress.log("Usage Metering ClusterServiceVersion not found")
                time.sleep(SLEEP_TIMER)
                if task_um is not None:
                    progress.advance(task_um)

            elif um_type == "HELM":
                um_release = um_details.get("helm_release", "ibm-usage-metering")
                progress.log(f"Running: helm uninstall {um_release}...")
                self._logger.info(f"Uninstalling Helm release: {um_release}")
                result = subprocess.run(
                    ["helm", "uninstall", um_release, "-n", self._namespace],
                    capture_output=True, text=True, check=False
                )
                if result.returncode != 0:
                    self._logger.warning(f"Helm uninstall failed, retrying with --no-hooks: {result.stderr}")
                    result = subprocess.run(
                        ["helm", "uninstall", um_release, "-n", self._namespace,
                         "--no-hooks", "--wait=false"],
                        capture_output=True, text=True, check=False
                    )
                if result.returncode != 0:
                    progress.log(Panel.fit(f"Failed to uninstall {um_release}: {result.stderr}", style="bold red"))
                    self._logger.error(f"helm uninstall failed for {um_release}: {result.stderr}")
                else:
                    progress.log(f"[green]✓[/green] Helm release {um_release} uninstalled")
                    self._logger.info(f"Helm release {um_release} uninstalled successfully")
                time.sleep(SLEEP_TIMER)
                if task_um is not None:
                    progress.advance(task_um)

            # 3. Standard/YAML resource cleanup (always run for OLM/YAML, and safe for Helm remnants)
            if um_type in ("YAML", "OLM"):
                progress.log("Deleting Usage Metering Kubernetes workloads and RBAC...")
                for um_name in ("ibm-usage-metering-instance", "ibm-usage-metering-operator"):
                    self._kube.delete_operator_deployment(namespace=self._namespace, name=um_name)
                    self._logger.info(f"Deleted deployment {um_name}")

                for um_name in ("ibm-usage-metering-instance", "ibm-usage-metering-leader-election",
                                "ibm-usage-metering-operator"):
                    self._kube.delete_role_binding(namespace=self._namespace, name=um_name)
                    self._kube.delete_role(namespace=self._namespace, name=um_name)
                    self._logger.info(f"Deleted role/rolebinding {um_name}")

                for um_sa in ("ibm-usage-metering-instance", "ibm-usage-metering-operator"):
                    self._kube.delete_service_account(namespace=self._namespace, name=um_sa)
                    self._logger.info(f"Deleted service account {um_sa}")

                self._kube.delete_service(namespace=self._namespace, name="ibm-usage-metering-instance")
                self._kube.delete_route(namespace=self._namespace, name="ibm-usage-metering-fetch")
                time.sleep(SLEEP_TIMER)
                if task_um is not None:
                    progress.advance(task_um)

            progress.log(Panel.fit("Uninstalling Usage Metering Operator completed!", style="bold green"))
            self._logger.info("Usage Metering Operator uninstallation completed!")
            if task_um is not None:
                progress.advance(task_um)
