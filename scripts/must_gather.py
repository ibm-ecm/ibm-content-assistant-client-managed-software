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

import datetime
import logging
import os
import re
import shutil
import tarfile
import toml
from datetime import datetime

import typer
import click
import questionary
from questionary import Style
from rich import print
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (BarColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text
from typing_extensions import Annotated
from threading import Lock

from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.mustgather import mustgather as mg
from helper_scripts.utilities import kubernetes_utilites as k
from helper_scripts.utilities.config_models import validate_mustgather_config
from helper_scripts.utilities.interface import (
    clear,
    display_issues,
    display_prereq_passed, mustgather_details, mustgather_network_results,
    display_config_validation_errors, display_prereq_validation_table,
    display_toml_syntax_error)
from helper_scripts.utilities.utilities import prereq_checks

def _get_version() -> str:
    try:
        import yaml
        _chart = os.path.join(os.path.dirname(__file__), "..", "helm-charts", "content-assistant", "Chart.yaml")
        with open(_chart) as f:
            return str(yaml.safe_load(f).get("version", "1.0.4"))
    except Exception:
        return "1.0.4"

__version__ = "1.4.0"

app = typer.Typer()

state = {
    "verbose": False,
    "silent": False,
    "logger": logging,
    "dev": False,
    "setup": None,
    "image_details": "",
    "dryrun": False
}

console = Console(record=True)


def setup_logger(file_log_level):
    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(file_log_level)

    # Setup console logger
    shell_handler = RichHandler(show_time=False, show_path=False)
    shell_handler.setLevel(logging.WARNING)
    formatter_rich = logging.Formatter("%(message)s")
    shell_handler.setFormatter(formatter_rich)

    # Setup file logger
    file_handler = logging.FileHandler("must_gather.log")
    file_handler.setLevel(file_log_level)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def version_callback(value: bool):
    if value:
        print(f"IBM Content Assistant MustGather CLI: {__version__}")
        raise typer.Exit()

def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.
    
    Args:
        mode: The operation mode (e.g., "Gather All", "Gather Network Policies")
        description: Description of what the script does
    """
    clear(console)
    print()
    
    # Create header table with version and mode info
    header_table = Table.grid(padding=(0, 2))
    header_table.add_column(style="cyan", justify="left")
    header_table.add_column(style="white", justify="left")
    
    # Add version and mode rows
    header_table.add_row("Version:", f"[bold green]{__version__}[/bold green]")
    header_table.add_row("Mode:", f"[bold yellow]{mode}[/bold yellow]")
    header_table.add_row("", f"[dim]{description}[/dim]")
    
    # Collect active flags
    active_flags = []
    
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
    
    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
    
    if state["dryrun"]:
        active_flags.append("🧪 Dry Run Mode")
    
    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")
    
    # Create the main panel with modern styling
    print(Panel(
        header_table,
        title="[bold white]📦 IBM Content Assistant MustGather CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()




# Mapping from internal component names to their deployment name patterns.
# Used when the deployment name doesn't contain the component name as a substring.
_COMPONENT_DEPLOYMENT_PATTERNS = {
    "genai_connector": "ibm-content-assistant",
}

# Function to filter deployments based on component
def filter_deployments(deployment, component):
    pattern = _COMPONENT_DEPLOYMENT_PATTERNS.get(component, component)
    return pattern in deployment


def create_mustgather_folder(progress, platform, components, collect_sensitive_data, cr_present=True,
                             operator_present=True):
    state["logger"].info("Creating MustGather folder")

    if os.path.exists(os.path.join(os.getcwd(), "MustGather")):
        shutil.rmtree(os.path.join(os.getcwd(), "MustGather"))

    mustgather_folder = os.path.join(os.getcwd(), "MustGather")

    os.mkdir(mustgather_folder)
    state["logger"].info(f"Created MustGather folder: {mustgather_folder}")

    state["logger"].info(f"Creating MustGather components subfolders")

    folder_names = [
        "cluster"
    ]

    if operator_present:
        folder_names.append("operator")

    if cr_present:
        folder_names.append("deployments")
        folder_names.append("services")
        folder_names.append("pvcs")
        folder_names.append("storageclasses")

        if platform == "other":
            folder_names.append("ingresses")
        else:
            folder_names.append("routes")

        folder_names.extend(components)

        if collect_sensitive_data:
            folder_names.extend(["secrets", "configmaps"])

    for folder_name in folder_names:
        os.mkdir(
            os.path.join(
                mustgather_folder,
                folder_name,
            )
        )
    
    state["logger"].info(f"Created MustGather components subfolders")
    return mustgather_folder



# Function to tar the mustgather folder
def tar_mustgather_folder(mustgather_folder, progress, namespace):
    try:
        namespace_no_spaces = re.sub(r"\s+", "", namespace)
        state["logger"].info(f"Generating MustGather tarfile")
        now = datetime.now()
        dt_string = now.strftime("%Y-%m-%d_%H-%M")
        tar_file_name = mustgather_folder + "_"  + namespace_no_spaces + "_" + dt_string + ".tar.gz"

        # Check if tar file exists move it to a backup folder
        if os.path.exists(tar_file_name):
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            shutil.move(tar_file_name, os.path.join(os.getcwd(), "backups",
                                                    "MustGather_" + namespace_no_spaces + "_" + dt_string + ".tar.gz"))

        with tarfile.open(tar_file_name, "w:gz") as tar:
            tar.add(mustgather_folder, arcname=os.path.basename(mustgather_folder))
        state["logger"].info(f"Generated MustGather tarfile: {tar_file_name}")
        shutil.rmtree(mustgather_folder)
        state["logger"].info(f"Removed MustGather folder: {mustgather_folder}")
    except Exception as e:
        state["logger"].exception("Unable to tar logs, caught %s Exiting...", e)

@app.callback(invoke_without_command=True)
def main(
        ctx: typer.Context,
        version: Annotated[bool, typer.Option(
            "--version", help="Show version and exit.",
            callback=version_callback, is_eager=True)] = None,
        verbose: Annotated[bool, typer.Option(
            help="Enable verbose logging.",
            rich_help_panel="Customization and Utils")] = False,
        silent: Annotated[bool, typer.Option(
            help="Enable Silent Install (no prompts).",
            rich_help_panel="Customization and Utils")] = False,
        dryrun: Annotated[bool, typer.Option(
            help="Perform Dry Run of the mustgather script",
            rich_help_panel="Customization and Utils")] = False):

    if ctx.invoked_subcommand == "networkpolicy":
        return
    """
    IBM Content Assistant MustGather
    """
    # Set up logger FIRST before any display functions
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.INFO

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if silent:
        state["silent"] = True

    if dryrun:
        state["dryrun"] = True
    
    # Now display the mode/version with flags properly set
    display_mode_version("Gather All",
                         "IBM Content Assistant MustGather for Container Deployment")
    
    # Display what will be collected
    info_text = Text()
    info_text.append("This mode will collect:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Cluster and namespace information\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Operator deployment details\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Custom Resource (CASCluster) configuration\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Pod logs and events\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Service and networking details\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Storage and PVC information\n", style="white")
    
    print(Panel(
        info_text,
        title="[bold white]📦 MustGather Collection[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    print()
    
    # Log script details after logger is set up
    log_msg = f"Version: {__version__}\nMode: Gather All\nIBM Content Assistant MustGather for Container Deployment"
    active_flags = []
    if state["silent"]:
        active_flags.append("Silent Mode is enabled")
    if state["verbose"]:
        active_flags.append("Verbose Logging is enabled")
    if state["dryrun"]:
        active_flags.append("Dry Run Mode is enabled")
    if active_flags:
        log_msg += "\n\n" + "\n".join(active_flags)
    state["logger"].info(f"Script details: \n{log_msg}")

    checks = ["connection"]

    state["logger"].info(f"Checking prerequisites")
    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks)

    # Print table of prerequisites that are missing
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        state["logger"].info(f"All prerequisites did not pass.")
        exit(1)
    else:
        state["logger"].info(f"All prerequisites passed.")
        display_prereq_validation_table(results)

    if state["silent"]:
        # this is the user details object which does pre-checks and collects some necessary details
        state["logger"].info(f"Executing in silent mode.")
        silent_path = os.path.join("silent_config", "silent_install_mustgather.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent mustgather configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)
            _success, _, _validation_errors = validate_mustgather_config(_config_dict)
            if not _success:
                print(display_config_validation_errors(_validation_errors, silent_path))
                raise typer.Exit(code=1)
            state["logger"].info("✓ Configuration validated successfully")
        except FileNotFoundError:
            print(Panel.fit(f"❌ Configuration file not found: {silent_path}", style="bold red"))
            raise typer.Exit(code=1)
        except typer.Exit:
            raise
        except toml.TomlDecodeError as _e:
            print(display_toml_syntax_error(_e, silent_path))
            raise typer.Exit(code=1)
        except Exception as _e:
            state["logger"].error(f"Unexpected error loading configuration: {str(_e)}")
            print(Panel.fit(f"❌ Unexpected error: {str(_e)}", style="bold red"))
            raise typer.Exit(code=1)

        setup = sg.SilentGatherOptions(state["logger"], silent_path, script_type="must_gather")
        setup.silent_parse_mustgather_operator_file()
    else:
        setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
        setup.collect_namespace()
        setup.collect_sensitive_data()

    namespace = setup.namespace
    collect_sensitive_data = setup.sensitive_collect

    kube = k.KubernetesUtilities(state["logger"])

    # Collect IBM Content Assistant operator details
    operator_deployment = "ibm-content-assistant-operator"
    state["logger"].info(f"Collecting Operator details for {operator_deployment}")
    operator_details = kube.get_operator_details(namespace, operator_deployment)
    operator_present = bool(operator_details)
    if operator_present:
        state["logger"].info(f"Found operator: {operator_deployment}")
    else:
        state["logger"].warning(f"Operator not found in namespace: {operator_deployment}")

    # Collect CR details
    state["logger"].info(f"Collecting CR details")
    custom_resources = kube.get_deployment_cr(namespace=namespace, logger=state["logger"])
    components = []
    deployment_details = {}

    if len(custom_resources) == 0:
        cr_present = False
        print("[prompt.invalid] No custom resources found.")
        state["logger"].info(f"No custom resources found.")
    else:
        cr_present = True
        deployment_details = kube.cr_details
        deployments = deployment_details.get("components", [])

        if not state["silent"]:
            state["logger"].info(f"Collecting mustgather components.")
            setup.collect_mustgather_components(deployments)
            components = list(setup.components)
            state["logger"].info(f"Components for mustgather: {components}")
        else:
            components = list(setup.components)

    all_operator_details = {"content-assistant": operator_details} if operator_present else {}
    summary = mustgather_details(deployment_details, components, all_operator_details, ["content-assistant"])

    print()
    print(summary)

    if not state["silent"]:
        proceed = questionary.confirm(
            f"🚀 Ready to collect MustGather data for IBM Content Assistant Operator. Proceed?",
            default=True,
            style=Style([
                ('question', 'fg:cyan bold'),
                ('answer', 'fg:green bold')
            ])
        ).ask()
        
        if not proceed:
            state["logger"].warning("MustGather cancelled by user")
            print()
            print(Panel.fit("❌ MustGather Collection Cancelled", style="yellow"))
            raise typer.Exit(code=1)
    
    if state["dryrun"]:
        print()
        print(Panel.fit("✓ Dry Run Complete - No Data Collected", style="green"))
        exit()

    print()
    print(Panel.fit("🔄 Starting MustGather Collection\nIBM Content Assistant Operator", style="bold cyan", border_style="cyan"))
    state["logger"].info("Starting MustGather for IBM Content Assistant Operator")

    # Initialize status tracking for Live display
    collection_status = {
        "Cluster Info": {"status": "⏳ Pending", "details": ""},
        "Operator Info": {"status": "⏳ Pending", "details": ""},
        "Deployment Artifacts": {"status": "⏳ Pending", "details": ""},
        "Component Logs": {"status": "⏳ Pending", "details": ""},
        "Tar File": {"status": "⏳ Pending", "details": ""}
    }
    status_lock = Lock()
    
    def create_collection_status_table():
        """Create a fresh status table with current collection status"""
        table = Table(
            title="📦 MustGather Collection Progress",
            show_header=True,
            header_style="bold cyan",
            border_style="cyan",
            title_style="bold cyan"
        )
        table.add_column("Collection Phase", style="cyan", width=25)
        table.add_column("Status", style="white", width=20)
        table.add_column("Details", style="white", width=50)
        
        for phase, info in collection_status.items():
            status = info["status"]
            details = info["details"]
            
            if "Complete" in status or "✓" in status:
                style = "green"
            elif "Collecting" in status or "🔄" in status:
                style = "yellow"
            elif "Error" in status or "✗" in status:
                style = "red"
            else:
                style = "dim white"
            
            table.add_row(
                phase,
                Text(status, style=style),
                Text(details, style="dim white" if not details else "white")
            )
        return table
    
    # Prepare platform and resource details
    platform = "OCP"
    if operator_present and operator_details.get("type") == "YAML":
        platform = "other"

    # Prepare CR details if present
    resource_type_dict = None
    pod_count_dict = {}
    num_collections = 0

    if cr_present:
        cr_name = deployment_details["name"]
        platform = deployment_details["platform"]
        storage_class = deployment_details["storage_classes"]
        user_secrets = deployment_details["user_secrets"]
        user_configmaps = deployment_details["user_configmaps"]

        resource_type_dict = kube.list_namespace_resources(console=console,
                                                           namespace=namespace,
                                                           filter=cr_name)

        # Build pod_count_dict for the genai_connector component
        for component in components:
            state["logger"].info(f"Getting deployments for component: {component}")
            deployment_dict_component = list(filter(
                lambda x: filter_deployments(x, component),
                resource_type_dict["deployment"]
            ))
            pod_count_dict[component] = []
            for deploy in deployment_dict_component:
                num_collections += 1
                details_dict = {}
                details_dict["deployment"] = deploy
                pods = kube.get_pod_names_for_deployment(namespace, deploy)
                init_containers = kube.get_init_containers_for_deployment(namespace, deploy)
                details_dict["init_containers"] = init_containers
                details_dict["pods"] = pods
                details_dict["count"] = len(pods) if pods else 0
                pod_count_dict[component].append(details_dict)
    
    # Use Live display for real-time status updates
    print()
    with Live(create_collection_status_table(), console=console, refresh_per_second=4) as live:
        # Create MustGather folder
        mustgather_folder = create_mustgather_folder(None, platform, components, collect_sensitive_data,
                                                     cr_present, operator_present)

        must_gather = mg.MustGather(console, namespace, state["logger"], mustgather_folder, deployment_details,
                                    operator_details, kube)

        # Phase 1: Collect Cluster Info
        with status_lock:
            collection_status["Cluster Info"]["status"] = "🔄 Collecting..."
            collection_status["Cluster Info"]["details"] = "Cluster version, nodes, events..."
            live.update(create_collection_status_table())

        state["logger"].info(f"Collecting cluster information")
        must_gather.collect_cluster_info(None)

        with status_lock:
            collection_status["Cluster Info"]["status"] = "✓ Complete"
            collection_status["Cluster Info"]["details"] = "Version, nodes, events collected"
            live.update(create_collection_status_table())

        # Phase 2: Collect Operator Info
        if operator_present:
            with status_lock:
                collection_status["Operator Info"]["status"] = "🔄 Collecting..."
                collection_status["Operator Info"]["details"] = "Collecting IBM Content Assistant Operator..."
                live.update(create_collection_status_table())

            state["logger"].info("Collecting IBM Content Assistant Operator information")

            with status_lock:
                collection_status["Operator Info"]["details"] = "RBAC resources..."
                live.update(create_collection_status_table())
            must_gather.collect_rbac_info(None, operator_details)

            with status_lock:
                collection_status["Operator Info"]["details"] = "Deployment & logs..."
                live.update(create_collection_status_table())
            must_gather.collect_operator_info(None, collect_sensitive_data, operator_details)

            with status_lock:
                collection_status["Operator Info"]["status"] = "✓ Complete"
                collection_status["Operator Info"]["details"] = "IBM Content Assistant Operator collected"
                live.update(create_collection_status_table())
        else:
            with status_lock:
                collection_status["Operator Info"]["status"] = "⊘ Skipped"
                collection_status["Operator Info"]["details"] = "No operator found"
                live.update(create_collection_status_table())

        # Phase 3: Collect Deployment Artifacts
        if cr_present and resource_type_dict:
            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "🔄 Collecting..."
                collection_status["Deployment Artifacts"]["details"] = "Custom Resource..."
                live.update(create_collection_status_table())

            # Download CASCluster CR file
            state["logger"].info(f"Downloading CASCluster CR file")
            must_gather.write_cr_file(None, deployment_details["name"])

            # Collect all Deployments
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = f"Deployments ({len(resource_type_dict['deployment'])})..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting all deployments")
            if len(resource_type_dict["deployment"]) > 0:
                deployments = resource_type_dict["deployment"]
                must_gather.collect_deployment_info(None, deployments)

            # Collect all PodDisruptionBudget Info
            state["logger"].info(f"Collecting PodDisruptionBudget (PDB) information")
            if resource_type_dict.get("pod_disruption_budget"):
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "PodDisruptionBudgets..."
                    live.update(create_collection_status_table())
                pdbs = resource_type_dict["pod_disruption_budget"]
                must_gather.collect_pdb_info(None, pdbs)

            # Collect all HorizontalPodAutoscaler Info
            state["logger"].info(f"Collecting HorizontalPodAutoscaler (HPA) information")
            if resource_type_dict.get("horizontal_pod_autoscaler"):
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "HorizontalPodAutoscalers..."
                    live.update(create_collection_status_table())
                hpas = resource_type_dict["horizontal_pod_autoscaler"]
                must_gather.collect_hpa_info(None, hpas)

            # Collect all StorageClass Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = "Storage Classes & PVCs..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting all storage class information")
            if len(storage_class) > 0:
                must_gather.collect_storage_class_info(None, storage_class)

            # Collect all PersistentVolume Info
            state["logger"].info(f"Collecting persistent volume information")
            if len(resource_type_dict["persistent_volume_claim"]) > 0:
                pvcs = resource_type_dict["persistent_volume_claim"]
                must_gather.collect_pvc_info(None, pvcs)

            # Collect all Service Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = f"Services ({len(resource_type_dict['service'])})..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting services information")
            if len(resource_type_dict["service"]) > 0:
                services = resource_type_dict["service"]
                must_gather.collect_service_info(None, services)

            # Collect all NetworkPolicy Info
            with status_lock:
                collection_status["Deployment Artifacts"]["details"] = "Network Policies..."
                live.update(create_collection_status_table())
            state["logger"].info(f"Collecting network policy information")
            if len(resource_type_dict["network_policy"]) > 0:
                network_policies = resource_type_dict["network_policy"]
                must_gather.collect_network_policy_info(None, network_policies)

            if platform == "other":
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Ingresses..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting ingresses information")
                if len(resource_type_dict.get("ingress", [])) > 0:
                    must_gather.collect_ingress_info(None, resource_type_dict["ingress"])
            else:
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Routes..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting routes information")
                if len(resource_type_dict.get("routes", [])) > 0:
                    must_gather.collect_route_info(None, resource_type_dict["routes"])

            if collect_sensitive_data:
                with status_lock:
                    collection_status["Deployment Artifacts"]["details"] = "Secrets & ConfigMaps..."
                    live.update(create_collection_status_table())
                state["logger"].info(f"Collecting secrets information")
                secrets = resource_type_dict["secret"]
                secrets.extend(user_secrets)
                if len(secrets) > 0:
                    must_gather.collect_secret_info(None, secrets)

                state["logger"].info(f"Collecting ConfigMaps information")
                configmaps = resource_type_dict["config_map"]
                configmaps.extend(user_configmaps)
                if len(configmaps) > 0:
                    must_gather.collect_configmap_info(None, configmaps)

            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "✓ Complete"
                collection_status["Deployment Artifacts"]["details"] = f"{len(resource_type_dict['deployment'])} deployments, {len(resource_type_dict['service'])} services"
                live.update(create_collection_status_table())
        else:
            with status_lock:
                collection_status["Deployment Artifacts"]["status"] = "⊘ Skipped"
                collection_status["Deployment Artifacts"]["details"] = "No CR found"
                live.update(create_collection_status_table())

        # Phase 4: Collect Component Logs
        if len(components) > 0 and num_collections > 0:
            with status_lock:
                collection_status["Component Logs"]["status"] = f"🔄 Collecting (0/{num_collections})..."
                live.update(create_collection_status_table())

            collected_count = 0
            for component in components:
                if component not in pod_count_dict or len(pod_count_dict[component]) == 0:
                    state["logger"].info(f"No Pods Found for {component}")
                else:
                    with status_lock:
                        collection_status["Component Logs"]["details"] = f"Collecting {component} logs..."
                        live.update(create_collection_status_table())
                    for deploy in pod_count_dict[component]:
                        must_gather.collect_genai_connector_info(None,
                                                                 collect_sensitive_data,
                                                                 deploy["pods"],
                                                                 deploy["init_containers"])
                        collected_count += 1
                        with status_lock:
                            collection_status["Component Logs"]["status"] = f"🔄 Collecting ({collected_count}/{num_collections})..."
                            live.update(create_collection_status_table())
            
            with status_lock:
                collection_status["Component Logs"]["status"] = "✓ Complete"
                collection_status["Component Logs"]["details"] = f"{num_collections} component deployments collected"
                live.update(create_collection_status_table())
        else:
            if len(components) > 0:
                state["logger"].info(f"No Pods Found for Selected Components")
            with status_lock:
                collection_status["Component Logs"]["status"] = "⊘ Skipped"
                collection_status["Component Logs"]["details"] = "No components or pods found"
                live.update(create_collection_status_table())
        
        # Phase 5: Create Tar File
        with status_lock:
            collection_status["Tar File"]["status"] = "🔄 Creating..."
            collection_status["Tar File"]["details"] = f"Compressing {namespace} MustGather..."
            live.update(create_collection_status_table())
        
        tar_mustgather_folder(mustgather_folder, None, namespace)
        
        with status_lock:
            collection_status["Tar File"]["status"] = "✓ Complete"
            collection_status["Tar File"]["details"] = f"MustGather_{namespace}.tar.gz created"
            live.update(create_collection_status_table())
    
    # Final summary
    print()
    print(Panel.fit("✓ MustGather Collection Complete", style="bold green"))
    print()

@app.command()
def networkpolicy(apply: bool = typer.Option(False, help="Apply all generated network policies to the cluster")):
    """
    Collect the Network policy templates from the IBM Content Assistant Operator
    """
    # Set up logger FIRST
    state["logger"] = setup_logger(logging.INFO)
    
    display_mode_version("Gather Network Policies",
                        "IBM Content Assistant MustGather for Container Deployment")
    
    # Display what will be collected
    info_text = Text()
    info_text.append("This mode will collect:\n\n", style="bold white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Network policy templates from operator\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Current network policy configurations\n", style="white")
    info_text.append("  ✓ ", style="bold green")
    info_text.append("Generate deployment-specific policies\n", style="white")
    if apply:
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Apply policies to cluster\n", style="white")
    
    print(Panel(
        info_text,
        title="[bold white]🔒 Network Policy Collection[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    print()

    checks = ["connection"]

    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks)
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        exit(1)
    else:
        state["logger"].info(f"All prerequisites passed.")
        display_prereq_validation_table(results)

    setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
    setup.collect_namespace()
    kube = k.KubernetesUtilities(state["logger"])
    deployment_details = {}

    # Collect Operator details
    operator_deployment = "ibm-content-assistant-operator"
    namespace = setup.namespace
    operator_details = kube.get_operator_details(namespace, operator_deployment)
    if not operator_details:
        print(Panel.fit(Text("IBM Content Assistant Operator not found in namespace."), style="bold red"))
        raise typer.Exit()
    np_folder = os.path.join(os.getcwd(), "CASNetworkPolicies", namespace)
    must_gather = mg.MustGather(console, namespace, state["logger"], np_folder, deployment_details, operator_details, kube)
    if apply:
        if os.path.exists(np_folder):
            print()
            print(Panel.fit(Text(f"Found {os.path.basename(np_folder)} Folder. Applying existing network policies"), style="cyan"))
            print()
            state["logger"].info(f"Found {os.path.basename(np_folder)} Folder. Applying existing network policies")
            must_gather.auto_apply_networkpolicy()
        else:
            print()
            print(Panel.fit(Text(f"{os.path.basename(np_folder)} Folder not found. Starting Copying Network policy Templates"), style="cyan"))
            print()
            state["logger"].info(f"Folder: {os.path.basename(np_folder)} not found. Applying existing network policies")
            with Progress(SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        transient=True,
                        console=console) as progress:
                if operator_details:
                    task1 = progress.add_task("[cyan]Collect Network Policies", total=None)
                    state["logger"].info(f"Collecting network policies")
                    must_gather.collect_network_policy_templates(progress, operator_details) 
                    progress.update(task1, total=1, completed=1)
                else:
                    print(Panel.fit(Text("IBM Content Assistant Operator not found in namespace."),style="bold red"))
                    state["logger"].info(f"IBM Content Assistant Operator not found in namespace.")
                    raise typer.Exit()

            # Output Network Policy Template folder
            print()
            print(Panel.fit(Text("Applying downloaded network policies"), style="cyan"))
            state["logger"].info(f"Applying downloaded network policies")
            print()
            must_gather.auto_apply_networkpolicy()
        raise typer.Exit()

    else:        
        setup = g.GatherOptions(state["logger"], console, script_type="must_gather")
        setup.collect_namespace()
        kube = k.KubernetesUtilities(state["logger"])

        deployment_details = {}

        # Collect Operator details
        operator_deployment = "ibm-content-assistant-operator"
        namespace = setup.namespace
        operator_details = kube.get_operator_details(namespace, operator_deployment)
        if not operator_details:
            print(Panel.fit(Text("IBM Content Assistant Operator not found in namespace."), style="bold red"))
            raise typer.Exit()
        np_folder = os.path.join(os.getcwd(), "CASNetworkPolicies", namespace)

        must_gather = mg.MustGather(console, namespace, state["logger"], np_folder, deployment_details,operator_details, kube)
        if os.path.exists(np_folder):
            namespace_no_spaces = re.sub(r"\s+", "", namespace)
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            tar_file_name = os.getcwd() + "/backups/" + "CASNetworkPolicies" + "_"  + namespace_no_spaces + "_" + dt_string + ".tar.gz"
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            try:
                with tarfile.open(tar_file_name, "w:gz") as tar:
                    tar.add(np_folder, arcname=os.path.basename(np_folder))
                    shutil.rmtree(np_folder)
            except Exception as e:
                 state["logger"].exception("Unable to tar network policies, caught %s Exiting...", e)

        if len(operator_details.get("pods", 0)) == 0:
            print()
            print(Panel.fit(Text("IBM Content Assistant Operator not found in namespace."), style="bold red"))
            state["logger"].info(f"IBM Content Assistant Operator not found in namespace.")
            raise typer.Exit()

        print()
        print(Panel.fit(Text("Starting Copying Network Policy Templates"), style="cyan"))
        print()
        state["logger"].info(f"Starting Copying Network Policy Templates")

        with Progress(SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    transient=True,
                    console=console) as progress:

            task1 = progress.add_task("[cyan]Collect Network Policies", total=None)
            must_gather.collect_network_policy_templates(progress,operator_details)
            progress.update(task1, total=1, completed=1)


        results = mustgather_network_results(np_folder, namespace)
        print(results)
        print()

        apply_networkpolicy = Confirm.ask("Do you want to apply the retrieved network policies to your cluster?", default=False)
        if apply_networkpolicy:
            state["logger"].info(f"Appliying the Network Policies.")
            must_gather.auto_apply_networkpolicy()
        raise typer.Exit()

if __name__ == "__main__":
    app()
