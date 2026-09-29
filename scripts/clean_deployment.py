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
"""
IBM Content Assistant Deployment Cleanup CLI

This script provides a modern, interactive interface for cleaning up IBM Content Assistant
deployments and operators from Kubernetes clusters.

Features:
    - Interactive cleanup with questionary prompts for better UX
    - Rich terminal output with progress bars and status indicators
    - Support for multiple operator types: YAML-based, OLM, and Helm
    - Multi-operator support: Clean up multiple operators in one operation
    - Two IBM Content Assistant operators supported:
        * Content Assistant Operator (ibm-content-assistant-operator)
        * Usage Metering Operator (ibm-usage-metering-operator)
    - Three cleanup modes:
        * Deployment only: Remove CR and workloads, keep operators
        * Operator only: Remove selected operators, keep deployments
        * Both: Complete cleanup of deployment and operators
    - Interactive operator selection with checkboxes
    - Dry run mode for safe preview of cleanup operations
    - Silent mode for automated/scripted cleanup
    - Comprehensive validation and error handling
    - Detailed completion summaries with next steps

Usage:
    # Interactive cleanup (both deployment and operators)
    python clean_deployment.py
    
    # Clean deployment only
    python clean_deployment.py deployment
    
    # Clean operators only (with interactive selection)
    python clean_deployment.py operator
    
    # Dry run mode
    python clean_deployment.py --dryrun
    
    # Silent mode (no prompts, cleans all detected operators)
    python clean_deployment.py --silent
    
    # Verbose logging
    python clean_deployment.py --verbose

Operator Types Supported:
    - YAML-based: Standard Kubernetes YAML deployments
    - OLM: Operator Lifecycle Manager installations
    - Helm: Helm chart deployments

Author: IBM Content Assistant Team
Version: 7.1.6
"""
import asyncio
import logging
import os
import time
import toml
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, List

import questionary
import typer
from rich import print
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TimeElapsedColumn,
    MofNCompleteColumn, BarColumn, TaskProgressColumn, TextColumn,
)
from rich.table import Table
from rich.text import Text
from rich.live import Live
from typing_extensions import Annotated

from helper_scripts.cleanup import cleanup as dc
from helper_scripts.gather import gather as g
from helper_scripts.gather import silent_gather as sg
from helper_scripts.utilities.cleanup_progress import (
    create_cleanup_progress,
    display_cleanup_complete,
    CleanupPhase,
    CleanupStep,
    DynamicRenderable
)
from helper_scripts.utilities.questionary_utils import handle_cancelled_prompt
from helper_scripts.utilities.config_models import validate_cleandeployment_config
from helper_scripts.utilities.interface import display_prereq_passed, display_issues, clear, \
    display_deployment_resources, display_config_validation_errors, display_prereq_validation_table, \
    display_toml_syntax_error
from helper_scripts.utilities.operator_config import OperatorType
from helper_scripts.utilities.utilities import prereq_checks, create_version_info, read_version_toml
from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities

__version__ = "1.4.0"

app = typer.Typer()

state = {
    "verbose": False,
    "silent": False,
    "logger": logging,
    "setup": None,
    "clean": None,
    "dryrun": False,
    "version_details": {}
}

console = Console(record=True)




def setup_logger(file_log_level):
    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Setup console logger
    shell_handler = RichHandler(show_time=False, show_path=False)
    shell_handler.setLevel(file_log_level)
    formatter_rich = logging.Formatter("%(message)s")
    shell_handler.setFormatter(formatter_rich)

    # Setup file logger
    file_handler = logging.FileHandler("cleandeployment.log")
    file_handler.setLevel(logging.DEBUG)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


def version_callback(value: bool):
    if value:
        print(f"IBM Content Assistant Cleanup CLI: {__version__}")
        raise typer.Exit()


def display_cleanup_completion(operator_cleaned: bool = False, deployment_cleaned: bool = False,
                               operator_type: Optional[str] = None, namespace: Optional[str] = None,
                               um_deployment_cleaned: bool = False, um_operator_cleaned: bool = False):
    """
    Display a completion summary after cleanup operations.

    Args:
        operator_cleaned: Whether the CAS operator was cleaned
        deployment_cleaned: Whether the CAS deployment (CR + workloads) was cleaned
        operator_type: Type of operator (OLM, Helm, YAML)
        namespace: Namespace where cleanup occurred
        um_deployment_cleaned: Whether the Usage Metering deployment was cleaned
        um_operator_cleaned: Whether the Usage Metering operator was cleaned
    """
    print()
    print()

    summary = Text()
    summary.append("✅ Cleanup Completed Successfully\n\n", style="bold green")

    if deployment_cleaned:
        summary.append("  ✓ ", style="bold green")
        summary.append("IBM Content Assistant Deployment removed\n", style="white")
        summary.append("  ✓ ", style="bold green")
        summary.append("All workloads and services deleted\n", style="white")

    if operator_cleaned:
        summary.append("  ✓ ", style="bold green")
        summary.append(f"IBM Content Assistant Operator removed ({operator_type})\n", style="white")
        summary.append("  ✓ ", style="bold green")
        summary.append("CRDs and RBAC resources cleaned\n", style="white")

    if um_deployment_cleaned:
        summary.append("  ✓ ", style="bold green")
        summary.append("Usage Metering deployment removed\n", style="white")

    if um_operator_cleaned:
        summary.append("  ✓ ", style="bold green")
        summary.append("Usage Metering operator removed\n", style="white")

    if namespace:
        summary.append("\n", style="white")
        summary.append(f"Namespace: ", style="bold cyan")
        summary.append(f"{namespace}\n", style="cyan")
    
    summary.append("\n", style="white")
    summary.append("💡 Next Steps:\n", style="bold yellow")
    summary.append("  • Verify resources are removed: ", style="white")
    summary.append(f"kubectl get all -n {namespace}\n", style="dim")
    
    if not operator_cleaned:
        summary.append("  • Operator still installed - run with 'operator' command to remove\n", style="yellow")
    
    print(Panel(
        summary,
        title="[bold white]🎉 Cleanup Summary[/bold white]",
        border_style="green",
        padding=(1, 2)
    ))


def detect_existing_installations(namespace: str, kube_utils, logger, console) -> dict:
    """
    Detect existing operator installations (OLM, Helm, and YAML-based).
    Adapted from deploy_operator.py for cleanup operations.
    Priority: Helm > OLM > YAML to show the actual installation method.
    
    Args:
        namespace: Target namespace to check
        kube_utils: Kubernetes utilities instance
        logger: Logger instance
        console: Rich console instance
        
    Returns:
        Dictionary with detection results for all 4 operators
    """
    result = {
        'has_olm': False,
        'has_helm': False,
        'olm_resources': {
            'csvs': [],
            'catalogs': []
        },
        'helm_releases': [],
        'operators': {}
    }
    
    # Operator definitions
    operators_to_check = {
        'content-assistant': {
            'deployment_name': 'ibm-content-assistant-operator',
            'helm_release': 'ibm-content-assistant-operator',
            'display_name': 'Content Assistant Operator'
        },
        'usage-metering': {
            'deployment_name': 'ibm-usage-metering-operator',
            'helm_release': 'ibm-usage-metering',
            'display_name': 'Usage Metering Operator'
        }
    }
    
    # Initialize operators as not detected
    for key, op_info in operators_to_check.items():
        result['operators'][key] = {
            'detected': False,
            'name': op_info['deployment_name'],
            'display_name': op_info['display_name'],
            'type': None,
            'helm_release': None,
            'details': {}
        }
    
    # Create progress display
    progress_table = Table.grid(padding=(0, 2))
    progress_table.add_column(style="cyan", width=40)
    progress_table.add_column(style="white")
    
    with Live(progress_table, console=console, refresh_per_second=10) as live:
        # Step 1: Check for Helm releases FIRST (highest priority)
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](1/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]Helm Releases[/white]")
        live.update(progress_table)
        
        for key, op_info in operators_to_check.items():
            try:
                # Check primary namespace
                cmd_result = subprocess.run(
                    ["helm", "list", "-n", namespace, "-o", "json"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                releases = json.loads(cmd_result.stdout)
                for release in releases:
                    if release.get("name") == op_info['helm_release']:
                        result['has_helm'] = True
                        helm_info = {
                            'name': op_info['helm_release'],
                            'display_name': op_info['display_name'],
                            'namespace': namespace,
                            'chart': release.get('chart', ''),
                            'status': release.get('status', ''),
                            'version': release.get('chart', '').split('-')[-1] if release.get('chart') else 'unknown'
                        }
                        result['helm_releases'].append(helm_info)
                        
                        # Mark operator as Helm-based
                        result['operators'][key]['detected'] = True
                        result['operators'][key]['type'] = 'Helm'
                        result['operators'][key]['helm_release'] = helm_info
                        logger.info(f"Found Helm release: {op_info['helm_release']}")
            except Exception as e:
                logger.debug(f"Error checking Helm release for {op_info['display_name']}: {e}")
        
        # Step 2: Detect OLM resources (second priority)
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](2/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]OLM Resources[/white]")
        live.update(progress_table)
        
        try:
            csv_prefixes = [
                "ibm-content-assistant-operator",
                "ibm-usage-metering"
            ]
            olm_resources = kube_utils.detect_olm_resources(namespace, csv_prefixes=csv_prefixes)
            if olm_resources.get('has_olm'):
                result['has_olm'] = True
                result['olm_resources'] = olm_resources
                
                # Mark operators as OLM-based if not already detected as Helm
                for csv in olm_resources.get('csvs', []):
                    csv_name = csv.get('name', '')
                    for key, op_info in operators_to_check.items():
                        if not result['operators'][key]['detected'] and op_info['deployment_name'] in csv_name:
                            result['operators'][key]['detected'] = True
                            result['operators'][key]['type'] = 'OLM'
                            logger.info(f"Found OLM CSV for {op_info['display_name']}")
                
                logger.info(f"Detected OLM resources: {len(olm_resources.get('csvs', []))} CSVs")
        except Exception as e:
            logger.debug(f"Error detecting OLM resources: {e}")
        
        # Step 3: Check for YAML-based deployments (lowest priority)
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](3/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Checking:[/cyan]", "[white]YAML Deployments[/white]")
        live.update(progress_table)
        
        for key, op_info in operators_to_check.items():
            # Only check if not already detected as Helm or OLM
            if not result['operators'][key]['detected']:
                try:
                    operator_details = kube_utils.get_operator_details(namespace, op_info['deployment_name'])
                    if operator_details:
                        result['operators'][key]['detected'] = True
                        result['operators'][key]['type'] = 'YAML'
                        result['operators'][key]['details'] = operator_details
                        logger.info(f"Found YAML deployment for {op_info['display_name']}")
                except Exception as e:
                    logger.debug(f"No YAML deployment found for {op_info['display_name']}: {e}")
        
        # Step 4: Complete
        progress_table = Table.grid(padding=(0, 2))
        progress_table.add_column(style="cyan", width=40)
        progress_table.add_column(style="white")
        progress_table.add_row(
            "[bold cyan]🔍 Detecting System State[/bold cyan]",
            "[dim](4/4)[/dim]"
        )
        progress_table.add_row("", "")
        progress_table.add_row("[cyan]Status:[/cyan]", "[green]Detection Complete[/green]")
        live.update(progress_table)
    
    return result


def display_system_dashboard(detection_results: dict, namespace: str, console, logger) -> None:
    """
    Display a comprehensive dashboard of the current system state.
    Adapted from deploy_operator.py for cleanup operations.
    
    Args:
        detection_results: Results from detect_existing_installations
        namespace: Target namespace
        console: Rich console instance
        logger: Logger instance
    """
    console.print()
    console.print()
    
    # Create main dashboard panel
    dashboard_content = []
    
    # Count detected operators
    detected_operators = sum(1 for op in detection_results['operators'].values() if op['detected'])
    
    # Consolidated System Overview with Operator Details
    overview_table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
    overview_table.add_column("Operator", style="cyan", width=35)
    overview_table.add_column("Status", style="white", width=15)
    overview_table.add_column("Type", style="green", width=15)
    
    for op_info in detection_results['operators'].values():
        if op_info['detected']:
            op_type = op_info.get('type', 'YAML')
            overview_table.add_row(
                op_info['display_name'],
                "[green]✓ Installed[/green]",
                op_type
            )
        else:
            overview_table.add_row(
                op_info['display_name'],
                "[dim]○ Not found[/dim]",
                "[dim]—[/dim]"
            )
    
    # Add summary footer
    overview_table.add_row("", "", "")  # Spacer
    if detected_operators > 0:
        overview_table.add_row(
            f"[bold]Total:[/bold]",
            f"[bold green]{detected_operators} operator(s)[/bold green]",
            f"[dim]Namespace: {namespace}[/dim]"
        )
    else:
        overview_table.add_row(
            f"[bold]Total:[/bold]",
            f"[bold yellow]No operators found[/bold yellow]",
            f"[dim]Namespace: {namespace}[/dim]"
        )
    
    dashboard_content.append(Panel(
        overview_table,
        title="[bold white]📊 System Overview[/bold white]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    # Helm Releases Section (if any found)
    if detection_results['has_helm'] and detection_results['helm_releases']:
        helm_table = Table(show_header=True, header_style="bold green", box=None, padding=(0, 1))
        helm_table.add_column("Release Name", style="green", width=35)
        helm_table.add_column("Chart", style="white", width=35)
        helm_table.add_column("Status", style="cyan", width=15)
        helm_table.add_column("Namespace", style="dim", width=20)
        
        for release in detection_results['helm_releases']:
            status_color = "green" if release['status'] == 'deployed' else "yellow"
            helm_table.add_row(
                release['name'],
                release['chart'],
                f"[{status_color}]{release['status']}[/{status_color}]",
                release['namespace']
            )
        
        dashboard_content.append(Panel(
            helm_table,
            title="[bold green]⎈ Helm Releases[/bold green]",
            border_style="green",
            padding=(1, 2)
        ))
    
    # Cleanup Plan Section
    plan_table = Table(show_header=False, box=None, padding=(0, 2))
    plan_table.add_column(style="white", width=100)
    
    if detected_operators > 0:
        plan_table.add_row(f"[green]✓[/green]  Ready to clean {detected_operators} operator(s)")
        if detection_results['has_olm']:
            plan_table.add_row("[blue]ℹ[/blue]  OLM resources will be removed")
        if detection_results['has_helm']:
            plan_table.add_row("[blue]ℹ[/blue]  Helm releases will be uninstalled")
    else:
        plan_table.add_row("[yellow]⚠[/yellow]  No operators found to clean")
    
    dashboard_content.append(Panel(
        plan_table,
        title="[bold white]📋 Cleanup Plan[/bold white]",
        border_style="blue",
        padding=(1, 2)
    ))
    
    # Display all dashboard sections
    for section in dashboard_content:
        console.print(section)
        console.print()
    
    logger.info("System dashboard displayed successfully")


def detect_all_operators(namespace: str, kube_utils, logger) -> dict:
    """
    Detect all IBM Content Assistant operators in the namespace.
    
    Args:
        namespace: Kubernetes namespace
        kube_utils: Kubernetes utilities instance
        logger: Logger instance
    
    Returns:
        dict: Dictionary of detected operators with their details
    """
    operators = {
        "content-assistant": {
            "name": "ibm-content-assistant-operator",
            "display_name": "Content Assistant Operator",
            "detected": False,
            "details": {}
        },
        "usage-metering": {
            "name": "ibm-usage-metering-operator",
            "display_name": "Usage Metering Operator",
            "detected": False,
            "details": {}
        }
    }
    
    for key, op_info in operators.items():
        logger.info(f"Checking for {op_info['display_name']}")
        details = kube_utils.get_operator_details(namespace, op_info["name"])
        if details:
            operators[key]["detected"] = True
            operators[key]["details"] = details
            logger.info(f"Found {op_info['display_name']}")
    
    return operators

def detect_existing_deployments(namespace: str, kube, logger) -> Dict[str, Dict]:
    """
    Detect all existing IBM Content Assistant deployments in the namespace.

    Args:
        namespace: Kubernetes namespace to check
        kube: Kubernetes utilities instance
        logger: Logger instance

    Returns:
        Dictionary of detected deployments with their details
    """
    deployments = {}

    # Check for Content Assistant CR (casclusters)
    try:
        logger.info("Checking for Content Assistant CR (casclusters)")
        content_cr = kube.get_deployment_cr(namespace=namespace, logger=logger)
        if content_cr:
            cr_name = content_cr.get("metadata", {}).get("name", "casdeploy")
            cr_version = content_cr.get("spec", {}).get("appVersion", "Unknown")
            deployments["content-assistant"] = {
                "type": "Content Assistant",
                "cr_name": cr_name,
                "version": cr_version,
                "group": "cas.ibm.com",
                "plural": "casclusters",
                "cr_data": content_cr
            }
            logger.info(f"Found Content Assistant CR: {cr_name} (v{cr_version})")
    except Exception as e:
        logger.debug(f"No Content Assistant CR found or error checking: {e}")

    # Check for Usage Metering CRs (ibmusagemeterings)
    try:
        logger.info("Checking for Usage Metering CR (ibmusagemeterings)")
        um_items = kube._custom_api.list_namespaced_custom_object(
            group="operator.ibm.com", version="v1",
            namespace=namespace, plural="ibmusagemeterings"
        ).get("items", [])
        for idx, um_cr in enumerate(um_items):
            cr_name = um_cr.get("metadata", {}).get("name", "ibmusagemetering")
            cr_version = um_cr.get("spec", {}).get("version", "Unknown")
            key = "usage-metering" if idx == 0 else f"usage-metering-{idx + 1}"
            deployments[key] = {
                "type": "Usage Metering",
                "cr_name": cr_name,
                "version": cr_version,
                "group": "operator.ibm.com",
                "api_version": "v1",
                "plural": "ibmusagemeterings",
                "cr_data": um_cr
            }
            logger.info(f"Found Usage Metering CR: {cr_name} (v{cr_version})")
    except Exception as e:
        logger.debug(f"No Usage Metering CR found or error checking: {e}")

    return deployments


def display_deployments_dashboard(deployments: Dict[str, Dict], namespace: str, console: Console, logger) -> None:
    """
    Display a modern dashboard showing detected deployments.
    
    Args:
        deployments: Dictionary of detected deployments
        namespace: Kubernetes namespace
        console: Rich console instance
        logger: Logger instance
    """
    if not deployments:
        console.print()
        console.print(Panel.fit(
            f"[yellow]No IBM Content Assistant deployments found in namespace:[/yellow] [cyan]{namespace}[/cyan]",
            border_style="yellow"
        ))
        return
    
    # Create header
    console.print()
    console.print(Panel(
        f"[bold white]Namespace:[/bold white] [cyan]{namespace}[/cyan]",
        title="[bold white]📦 Detected Deployments[/bold white]",
        border_style="bright_blue",
        padding=(1, 2)
    ))
    console.print()
    
    # Create deployments table
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="bright_blue",
        title="Custom Resources (CRs)",
        title_style="bold white"
    )
    
    table.add_column("Type", style="cyan", width=20)
    table.add_column("CR Name", style="white", width=25)
    table.add_column("Version", style="green", width=15)
    table.add_column("Status", justify="center", width=15)
    
    for dep_key, dep_info in deployments.items():
        status_icon = "[green]✓ Active[/green]"
        table.add_row(
            dep_info["type"],
            dep_info["cr_name"],
            dep_info["version"],
            status_icon
        )

    console.print(table)
    console.print()
    logger.info(f"Deployments dashboard displayed successfully")

def prompt_deployment_selection(detected_deployments: dict) -> list:
    """
    Prompt user to select which deployments to clean up using checkboxes.
    
    Args:
        detected_deployments: Dictionary of detected deployments
    
    Returns:
        list: List of deployment keys selected for cleanup
    """
    print()
    print(Panel.fit(
        "Multiple deployments detected. Select which deployments to clean up:",
        border_style="cyan"
    ))
    print()
    
    # Create choices for questionary
    choices = []
    for dep_key, dep_info in detected_deployments.items():
        choice_text = f"{dep_info['type']} - {dep_info['cr_name']} (v{dep_info['version']})"
        choices.append(questionary.Choice(
            title=choice_text,
            value=dep_key,
            checked=True  # Pre-select all by default
        ))
    
    # Add "Select All" and "Deselect All" options
    choices.insert(0, questionary.Separator("═" * 60))
    
    selected = questionary.checkbox(
        "Select deployments to clean up (Space to toggle, Enter to confirm):",
        choices=choices,
        style=questionary.Style([
            ('checkbox', 'fg:cyan'),
            ('checkbox-selected', 'fg:green bold'),
            ('pointer', 'fg:cyan bold'),
            ('highlighted', 'fg:cyan bold'),
            ('selected', 'fg:green'),
            ('separator', 'fg:#666666'),
        ])
    ).ask()
    
    if selected is None:  # User pressed Ctrl+C
        print("\n[yellow]⚠️  Deployment cleanup cancelled by user[/yellow]")
        exit(0)
    
    return selected

def display_cleanup_scope_info(console: Console) -> None:
    """
    Display information about what will and won't be cleaned up during deployment cleanup.
    Provides clear guidance on manual cleanup steps required.
    
    Args:
        console: Rich console instance
    """
    from rich.rule import Rule
    
    console.print()
    console.print(Rule("[bold cyan]📋 Cleanup Scope Information[/bold cyan]", style="cyan"))
    console.print()
    
    # What will be cleaned
    will_clean = Panel(
        "[bold white]The following will be removed:[/bold white]\n\n"
        "  [green]✓[/green] Custom Resource (CR)\n"
        "  [green]✓[/green] Deployments and StatefulSets\n"
        "  [green]✓[/green] Pods and Services\n"
        "  [green]✓[/green] ConfigMaps and Secrets (generated)\n"
        "  [green]✓[/green] Routes and Ingress (generated)\n"
        "  [green]✓[/green] Network Policies",
        title="[bold green]Automated Cleanup[/bold green]",
        border_style="green",
        padding=(1, 2)
    )
    
    # What won't be cleaned
    wont_clean = Panel(
        "[bold white]The following will NOT be removed:[/bold white]\n\n"
        "  [yellow]⚠[/yellow]  Custom Resource Definitions (CRDs)\n"
        "  [yellow]⚠[/yellow]  Persistent Volumes (PVs) and Claims (PVCs)\n"
        "  [yellow]⚠[/yellow]  Database data and schemas\n"
        "  [yellow]⚠[/yellow]  LDAP configurations\n"
        "  [yellow]⚠[/yellow]  Namespace\n"
        "  [yellow]⚠[/yellow]  Operators (use 'operator' command)\n\n"
        "[dim]These must be cleaned up manually if needed[/dim]",
        title="[bold yellow]Manual Cleanup Required[/bold yellow]",
        border_style="yellow",
        padding=(1, 2)
    )
    
    # Display side by side
    from rich.columns import Columns
    console.print(Columns([will_clean, wont_clean], equal=True, expand=True))
    console.print()
    
    # Important notes
    notes = Panel(
        "[bold white]📌 Important Notes:[/bold white]\n\n"
        "  [cyan]1.[/cyan] CR will be backed up to [white]./cr-backups/[/white] before deletion\n"
        "  [cyan]2.[/cyan] Run [white]python must_gather.py[/white] before cleanup for diagnostics\n"
        "  [cyan]3.[/cyan] PVs/PVCs must be deleted manually: [white]kubectl delete pvc -n <namespace>[/white]\n"
        "  [cyan]4.[/cyan] Database cleanup is manual - consult your DBA\n"
        "  [cyan]5.[/cyan] Namespace deletion is manual: [white]kubectl delete namespace <namespace>[/white]",
        title="[bold cyan]💡 Recommendations[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    )
    console.print(notes)
    console.print()


def backup_cr_before_deletion(cr_data: dict, cr_name: str, cr_type: str, namespace: str, logger) -> str:
    """
    Backup a Custom Resource to a YAML file before deletion.
    
    Args:
        cr_data: The CR data dictionary
        cr_name: Name of the CR
        cr_type: Type of CR ("Content" or "AI Services")
        namespace: Kubernetes namespace
        logger: Logger instance
        
    Returns:
        Path to the backup file
    """
    import yaml
    from datetime import datetime
    
    # Create backup directory
    backup_dir = os.path.join(os.getcwd(), "cr-backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = cr_type.lower().replace(" ", "-")
    filename = f"{safe_type}_{cr_name}_{namespace}_{timestamp}.yaml"
    filepath = os.path.join(backup_dir, filename)
    
    # Write CR to YAML file
    try:
        with open(filepath, 'w') as f:
            yaml.dump(cr_data, f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Backed up {cr_type} CR to: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to backup CR: {e}")
        raise





def prompt_operator_selection(detected_operators: dict) -> list:
    """
    Prompt user to select which operators to clean up using checkboxes.
    
    Args:
        detected_operators: Dictionary of detected operators
    
    Returns:
        list: List of operator keys selected for cleanup
    """
    print()
    print(Panel.fit(
        "Multiple operators detected. Select which operators to clean up:",
        border_style="cyan"
    ))
    print()
    
    choices = []
    for key, op_info in detected_operators.items():
        if op_info["detected"]:
            # Get type directly from op_info (not from details)
            op_type = op_info.get("type", "YAML")
            choices.append(
                questionary.Choice(
                    title=f"{op_info['display_name']} ({op_type})",
                    value=key,
                    checked=True  # Default to all selected
                )
            )
    
    if not choices:
        return []
    
    selected = questionary.checkbox(
        "Select operators to clean up (Space to toggle, Enter to confirm):",
        choices=choices,
        style=questionary.Style([
            ('selected', 'fg:green bold'),
            ('question', 'bold'),
            ('pointer', 'fg:cyan bold'),
        ])
    ).ask()
    
    return selected if selected else []


def prompt_cleanup_mode():
    """
    Prompt user to select cleanup mode when no subcommand is provided.
    
    Returns:
        str: Selected mode ('both', 'deployment', 'operator', 'cancel')
    """
    print()
    choices = [
        questionary.Choice(
            title="🧹 Clean Both (Deployment + Operator)",
            value="both",
            description="Remove deployment and operator completely"
        ),
        questionary.Choice(
            title="📦 Clean Deployment Only",
            value="deployment",
            description="Remove deployment, keep operator installed"
        ),
        questionary.Choice(
            title="⚙️  Clean Operator Only",
            value="operator",
            description="Remove operator, deployments will remain"
        ),
        questionary.Choice(
            title="❌ Cancel",
            value="cancel",
            description="Exit without making changes"
        ),
    ]
    
    mode = questionary.select(
        "What would you like to clean?",
        choices=choices,
        style=questionary.Style([
            ('highlighted', 'fg:cyan bold'),
            ('question', 'bold'),
            ('pointer', 'fg:cyan bold'),
        ])
    ).ask()
    
    return mode if mode else "cancel"


# Create a function to display the mode and version
def display_mode_version(mode: str, description: str):
    """
    Display the mode and version of the script in a modern, visually appealing format.
    
    Args:
        mode: The operation mode
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
    if state["dryrun"]:
        active_flags.append("🔍 Dry Run")
    
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
    
    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")
    
    # Create the main panel with modern styling
    print(Panel(
        header_table,
        title="[bold white]🧹 IBM Content Assistant Cleanup CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False
    ))
    print()


# main function
@app.command()
def operator():
    """
        Uninstall IBM Content Assistant Operators.
        Supports cleanup of Content Assistant and Usage Metering operators.
    """
    # Detect all installations and display system dashboard
    namespace = state["clean"]._deployment_prerequisites.namespace
    
    print()
    print(Panel.fit(
        "Analyzing current system state...",
        border_style="cyan"
    ))
    
    detection_results = detect_existing_installations(
        namespace=namespace,
        kube_utils=state["clean"]._kube,
        logger=state['logger'],
        console=console
    )
    
    # Display comprehensive system dashboard
    display_system_dashboard(detection_results, namespace, console, state['logger'])
    
    # Check if any operators are detected
    detected_count = sum(1 for op in detection_results['operators'].values() if op["detected"])
    if detected_count == 0:
        print()
        print(Panel.fit(f"No IBM Content Assistant Operators found in {namespace}", border_style="red"))
        state['logger'].info(f"No IBM Content Assistant Operators found in {namespace}")
        exit()
    
    # Convert detection results to the format expected by the rest of the function
    all_operators = detection_results['operators']
    
    # Select operators to clean (interactive mode only)
    if not state["silent"]:
        selected_operators = prompt_operator_selection(all_operators)
        
        if not selected_operators:
            print("\n[yellow]⚠️  No operators selected for cleanup[/yellow]")
            exit(0)
    else:
        # In silent mode, clean all detected operators (respecting CLEANUP_USAGE_METERING for usage-metering)
        cleanup_um = getattr(state["setup"], "cleanup_usage_metering", False)
        selected_operators = []
        for key, op in all_operators.items():
            if op["detected"]:
                if key == "usage-metering" and not cleanup_um:
                    continue
                selected_operators.append(key)
    
    # Display what will be cleaned
    print()
    cleanup_info = Text()
    cleanup_info.append("The following operators will be removed:\n\n", style="bold white")
    for op_key in selected_operators:
        op_info = all_operators[op_key]
        cleanup_info.append(f"  ✓ ", style="bold green")
        cleanup_info.append(f"{op_info['display_name']}\n", style="white")
    
    print(Panel(
        cleanup_info,
        title="[bold white]🧹 Cleanup Plan[/bold white]",
        border_style="yellow",
        padding=(1, 2)
    ))
    
    # Confirm cleanup
    if not state["silent"]:
        print()
        clean_operators = questionary.confirm(
            f"Do you want to proceed and cleanup {len(selected_operators)} operator(s)?",
            default=False,
            style=questionary.Style([
                ('question', 'bold'),
                ('answer', 'fg:green bold'),
            ])
        ).ask()
        
        if clean_operators is None:  # User pressed Ctrl+C
            print("\n[yellow]⚠️  Cleanup cancelled by user[/yellow]")
            exit(0)
    else:
        clean_operators = True

    if state["dryrun"]:
        print()
        print(Panel.fit(
            "🔍 Dry run completed - no resources were deleted",
            border_style="green"
        ))
        exit(0)

    if clean_operators:
        clear(console)
        
        # Prepare operators dict for cleanup tracker
        operators_to_clean = {
            op_key: all_operators[op_key]
            for op_key in selected_operators
        }
        
        # Determine if we should use parallel cleanup (2+ operators)
        use_parallel = len(selected_operators) > 1
        
        # Create cleanup progress tracker
        tracker, live = create_cleanup_progress(
            operators=operators_to_clean,
            parallel=use_parallel,
            console=console
        )
        
        # Track executor for cleanup
        executor = None
        
        try:
            # Start live display
            live.start()
            
            def cleanup_single_operator(op_key: str) -> bool:
                """Clean up a single operator."""
                op_info = all_operators[op_key]
                state["logger"].info(f"Cleaning operator: {op_key}")
                
                # Update tracker - preparing
                tracker.update_operator(
                    op_key,
                    phase=CleanupPhase.PREPARING,
                    step=CleanupStep.OPERATOR_DELETION,
                    progress=10
                )
                live.update(tracker.create_progress_display())
                
                # Get type from op_info
                op_type = op_info.get("type", "YAML")
                
                # Determine task count based on type
                if op_type == "OLM":
                    operator_task_num = 4
                elif op_type == "Helm":
                    operator_task_num = 3
                else:
                    operator_task_num = 5
                
                try:
                    # Update tracker - cleaning
                    tracker.update_operator(
                        op_key,
                        phase=CleanupPhase.CLEANING,
                        progress=30
                    )
                    live.update(tracker.create_progress_display())
                    
                    # Handle Helm operators differently
                    if op_type == "Helm":
                        # Helm cleanup using helm uninstall
                        namespace = state["clean"]._deployment_prerequisites.namespace
                        if not namespace:
                            raise Exception("Namespace not found in deployment prerequisites")
                        
                        # Map operator keys to Helm release names
                        helm_release_map = {
                            "content-assistant": "ibm-content-assistant-operator",
                            "usage-metering": "ibm-usage-metering"
                        }
                        
                        release_name = helm_release_map.get(op_key)
                        if not release_name:
                            release_name = op_info.get("name", "unknown")
                        
                        # Step 1: Helm uninstall
                        tracker.update_operator(
                            op_key,
                            step=CleanupStep.HELM_UNINSTALL,
                            progress=40
                        )
                        live.update(tracker.create_progress_display())
                        
                        state["logger"].info(f"Uninstalling Helm release: {release_name}")
                        
                        # Try normal uninstall first
                        result = subprocess.run(
                            ["helm", "uninstall", release_name, "-n", namespace],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        # If normal uninstall fails, try with --no-hooks and --wait=false
                        if result.returncode != 0:
                            state["logger"].warning(f"Normal uninstall failed, trying with --no-hooks: {result.stderr}")
                            result = subprocess.run(
                                ["helm", "uninstall", release_name, "-n", namespace, "--no-hooks", "--wait=false"],
                                capture_output=True,
                                text=True,
                                check=False
                            )
                        
                        # If still failing, try to manually clean up resources
                        if result.returncode != 0:
                            state["logger"].warning(f"Helm uninstall with --no-hooks failed, attempting manual cleanup: {result.stderr}")
                            
                            # Get all resources managed by this Helm release
                            try:
                                # List all resources with the Helm release label
                                label_selector = f"app.kubernetes.io/instance={release_name}"
                                
                                # Delete deployments
                                subprocess.run(
                                    ["kubectl", "delete", "deployment", "-n", namespace, "-l", label_selector, "--ignore-not-found=true"],
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                # Delete services
                                subprocess.run(
                                    ["kubectl", "delete", "service", "-n", namespace, "-l", label_selector, "--ignore-not-found=true"],
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                # Delete configmaps
                                subprocess.run(
                                    ["kubectl", "delete", "configmap", "-n", namespace, "-l", label_selector, "--ignore-not-found=true"],
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                # Delete secrets (Helm release secrets)
                                subprocess.run(
                                    ["kubectl", "delete", "secret", "-n", namespace, "-l", f"owner=helm,name={release_name}", "--ignore-not-found=true"],
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                state["logger"].info(f"Manual cleanup completed for {release_name}")
                                
                            except Exception as cleanup_error:
                                state["logger"].error(f"Manual cleanup failed: {cleanup_error}")
                                error_msg = f"Helm uninstall and manual cleanup failed: {result.stderr}"
                                raise Exception(error_msg)
                        
                        # Step 2: Remove CRDs if needed
                        tracker.update_operator(
                            op_key,
                            step=CleanupStep.CRD_DELETION,
                            progress=70
                        )
                        live.update(tracker.create_progress_display())
                        
                        state["logger"].info(f"Checking for CRDs to remove")
                        # CRDs are typically left behind by Helm, clean them if needed
                        # This is optional and depends on the operator
                        
                        # Step 3: Verification
                        tracker.update_operator(
                            op_key,
                            step=CleanupStep.VERIFICATION,
                            progress=90
                        )
                        live.update(tracker.create_progress_display())
                        
                        state["logger"].info(f"Verifying cleanup of {release_name}")
                        # Verify the release is gone
                        verify_result = subprocess.run(
                            ["helm", "list", "-n", namespace, "-q"],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        stdout_output = verify_result.stdout or ""
                        if release_name in stdout_output:
                            raise Exception(f"Helm release {release_name} still exists after uninstall")
                        
                    else:
                        # YAML or OLM cleanup using existing delete_operator method
                        # Create a simple progress tracker for the cleanup operation
                        class SimpleProgress:
                            def __init__(self, tracker, live, op_key):
                                self.tracker = tracker
                                self.live = live
                                self.op_key = op_key
                                self.current_step = 0
                                self.total_steps = operator_task_num
                            
                            def advance(self, task_id):
                                self.current_step += 1
                                progress_pct = int((self.current_step / self.total_steps) * 70) + 30
                                self.tracker.update_operator(
                                    self.op_key,
                                    progress=min(progress_pct, 95)
                                )
                                self.live.update(self.tracker.create_progress_display())
                            
                            def log(self, message=""):
                                # Log to file only, not to console (Live display handles that)
                                if message:
                                    state["logger"].debug(str(message))
                            
                            @property
                            def finished(self):
                                return self.current_step >= self.total_steps
                        
                        simple_progress = SimpleProgress(tracker, live, op_key)
                        
                        # Temporarily update state for this operator
                        old_operator_details = state["clean"]._operator_details
                        operator_details = op_info.get("details", {})
                        if not operator_details:
                            operator_details = {
                                "type": op_type,
                                "deployment": op_info["name"]
                            }
                        state["clean"]._operator_details = operator_details
                        
                        # Perform cleanup
                        task_id = 1  # Dummy task ID for compatibility
                        while not simple_progress.finished:
                            state["clean"].delete_operator(task_id, simple_progress)
                        
                        # Restore original operator details
                        state["clean"]._operator_details = old_operator_details
                    
                    # Mark as complete
                    tracker.complete_operator(op_key, success=True)
                    live.update(tracker.create_progress_display())
                    return True
                    
                except Exception as e:
                    error_msg = f"Cleanup failed: {str(e)}"
                    state["logger"].error(f"Error cleaning {op_key}: {error_msg}")
                    tracker.complete_operator(
                        op_key,
                        success=False,
                        error=error_msg
                    )
                    live.update(tracker.create_progress_display())
                    return False
            
            # Clean operators in parallel or sequential mode
            if use_parallel:
                # Calculate max workers
                max_workers = min(len(selected_operators), 4)  # Max 4 parallel cleanups
                
                async def cleanup_operators_parallel():
                    loop = asyncio.get_running_loop()
                    nonlocal executor
                    executor = ThreadPoolExecutor(max_workers=max_workers)
                    try:
                        tasks = []
                        
                        # Add all operators as individual tasks
                        for op_key in selected_operators:
                            # Mark as started
                            tracker.start_operator(op_key)
                            tasks.append(loop.run_in_executor(executor, cleanup_single_operator, op_key))
                        
                        results = await asyncio.gather(*tasks)
                        return all(results)
                    except asyncio.CancelledError:
                        state["logger"].info("Async tasks cancelled, shutting down executor...")
                        if executor:
                            executor.shutdown(wait=False)
                            executor = None
                        raise
                    finally:
                        if executor:
                            executor.shutdown(wait=True)
                            executor = None
                
                try:
                    all_success = asyncio.run(cleanup_operators_parallel())
                except KeyboardInterrupt:
                    raise  # Re-raise to be caught by outer handler
            else:
                # Sequential cleanup
                all_success = True
                for op_key in selected_operators:
                    tracker.start_operator(op_key)
                    success = cleanup_single_operator(op_key)
                    if not success:
                        all_success = False
            
            # Stop live display
            live.stop()
            
            # Mark overall completion
            tracker.overall_end_time = tracker.overall_start_time.__class__.now()
            
            # Display completion summary
            display_cleanup_complete(tracker, console)
            
        except KeyboardInterrupt:
            state["logger"].warning("Cleanup interrupted by user (Ctrl+C)")
            console.print()
            console.print(Panel.fit(
                "⚠️  Cleanup interrupted by user\n\n"
                "Cleaning up resources and shutting down gracefully...",
                title="[bold yellow]Keyboard Interrupt[/bold yellow]",
                border_style="yellow"
            ))
            
            # Shutdown executor if it exists
            if executor:
                state["logger"].info("Shutting down thread pool executor...")
                executor.shutdown(wait=False)
            
            # Stop live display
            if live._started:
                live.stop()
            
            # Mark incomplete operators as failed
            for op_key in selected_operators:
                if not tracker.statuses[op_key].is_complete:
                    tracker.complete_operator(
                        op_key,
                        success=False,
                        error="Interrupted by user"
                    )
            
            # Display partial results
            console.print()
            console.print(Panel.fit(
                "Cleanup was interrupted. Some operators may have been partially cleaned.",
                title="[bold yellow]⚠️  Partial Cleanup[/bold yellow]",
                border_style="yellow"
            ))
            
            exit(1)


@app.command()
def deployment():
    """
    Uninstall IBM Content Assistant Deployments (Content Assistant CRs).
    
    This command detects and removes Custom Resources (CRs) and their associated
    workloads while keeping operators installed. Supports:
    - Content Assistant CR (casclusters)
    - Multi-CR selection with checkboxes
    - Parallel cleanup (optional)
    """
    namespace = state["clean"]._deployment_prerequisites.namespace
    kube = KubernetesUtilities(state['logger'])
    
    # Step 1: Detect existing deployments (both Content and AI Services CRs)
    state['logger'].info("Detecting existing deployments...")
    detected_deployments = detect_existing_deployments(
        namespace=namespace,
        kube=kube,
        logger=state['logger']
    )
    
    # Step 2: Check if any deployments found
    if not detected_deployments:
        print()
        print(Panel.fit(
            f"[yellow]No IBM Content Assistant deployments found in namespace:[/yellow] [cyan]{namespace}[/cyan]",
            border_style="yellow"
        ))
        state['logger'].info(f"No IBM Content Assistant deployments found in {namespace}")
        exit(0)
    
    # Step 3: Display modern dashboard
    display_deployments_dashboard(
        deployments=detected_deployments,
        namespace=namespace,
        console=console,
        logger=state['logger']
    )
    
    # Step 3.5: Display cleanup scope information (what will/won't be cleaned)
    if not state["silent"]:
        display_cleanup_scope_info(console)

    # Step 3.6: Warn about Usage Metering before the selection prompt so the
    # user can make an informed choice in the checkbox that follows.
    if not state["silent"] and any(
        v["type"] == "Usage Metering" for v in detected_deployments.values()
    ):
        print()
        print(Panel.fit(
            "[yellow]⚠  Usage Metering deployment detected[/yellow]\n\n"
            "Usage Metering may be shared with other deployments in this namespace.\n"
            "Deleting it will affect any other products that rely on it.\n"
            "Deselect it in the next step if you want to keep it.",
            border_style="yellow"
        ))

    # Step 4: Select deployments to clean (if multiple)
    selected_deployments = []
    if len(detected_deployments) > 1 and not state["silent"]:
        selected_deployments = prompt_deployment_selection(detected_deployments)

        if not selected_deployments:
            print("\n[yellow]⚠️  No deployments selected for cleanup[/yellow]")
            exit(0)
    else:
        # Single deployment or silent mode - select all (excluding usage-metering if cleanup_usage_metering is False in silent mode)
        cleanup_um = getattr(state["setup"], "cleanup_usage_metering", False)
        selected_deployments = []
        for k, v in detected_deployments.items():
            if state["silent"] and v.get("type") == "Usage Metering" and not cleanup_um:
                continue
            selected_deployments.append(k)
    
    # Step 5: Confirm cleanup (unless silent or dryrun)
    if not state["silent"] and not state["dryrun"]:
        print()
        deployment_names = ", ".join([detected_deployments[k]["cr_name"] for k in selected_deployments])
        clean_deployment = questionary.confirm(
            f"Do you want to proceed and cleanup {len(selected_deployments)} deployment(s): {deployment_names}?",
            default=False,
            style=questionary.Style([
                ('question', 'bold'),
                ('answer', 'fg:green bold'),
            ])
        ).ask()
        
        if clean_deployment is None:  # User pressed Ctrl+C
            print("\n[yellow]⚠️  Cleanup cancelled by user[/yellow]")
            exit(0)
        
        if not clean_deployment:
            print("\n[yellow]⚠️  Cleanup cancelled by user[/yellow]")
            exit(0)
    
    # Step 6: Handle dry run mode
    if state["dryrun"]:
        print()
        print(Panel.fit(
            f"🔍 Dry run completed - {len(selected_deployments)} deployment(s) would be deleted:\n" +
            "\n".join([f"  • {detected_deployments[k]['type']}: {detected_deployments[k]['cr_name']}"
                      for k in selected_deployments]),
            border_style="green"
        ))
        exit(0)
    
    # Step 7: Perform cleanup with modern progress tracking
    clear(console)
    
    # Create deployment cleanup tracker
    from helper_scripts.utilities.cleanup_progress import (
        DeploymentCleanupTracker,
        DeploymentCleanupPhase,
        display_deployment_cleanup_complete
    )
    
    # Filter to only selected deployments
    deployments_to_clean = {k: v for k, v in detected_deployments.items() if k in selected_deployments}
    
    # Determine if parallel cleanup (for now, sequential is safer for CRs)
    use_parallel = False  # Can be enabled with --parallel flag in future
    
    tracker = DeploymentCleanupTracker(
        deployments=deployments_to_clean,
        console=console,
        parallel=use_parallel
    )
    
    # Create live display
    live = Live(
        DynamicRenderable(tracker.create_progress_display),
        console=console,
        refresh_per_second=4,
        transient=False
    )
    
    executor = None
    
    try:
        live.start()
        
        def cleanup_single_deployment(dep_key: str) -> bool:
            """Clean up a single deployment CR."""
            try:
                dep_info = deployments_to_clean[dep_key]
                
                # Mark as started
                tracker.update_deployment(
                    dep_key,
                    phase=DeploymentCleanupPhase.PREPARING,
                    progress=10
                )
                live.update(tracker.create_progress_display())
                
                # Create a simple progress tracker for the delete_CR method
                class SimpleProgress:
                    def __init__(self, tracker, dep_key, live_display):
                        self.tracker = tracker
                        self.dep_key = dep_key
                        self.live = live_display
                        self.finished = False
                        self.step_count = 0
                        self.total_steps = 8
                    
                    def log(self, message=""):
                        """Log a message (update current step)."""
                        msg = str(message).strip()
                        if msg and not msg.startswith("\n"):
                            self.tracker.update_deployment(
                                self.dep_key,
                                step=msg[:50]  # Truncate long messages
                            )
                            self.live.update(self.tracker.create_progress_display())
                    
                    def advance(self, task_id):
                        """Advance progress."""
                        self.step_count += 1
                        progress_pct = int((self.step_count / self.total_steps) * 90) + 10  # 10-100%
                        
                        # Update phase based on progress
                        if progress_pct < 30:
                            phase = DeploymentCleanupPhase.DELETING_CR
                        elif progress_pct < 80:
                            phase = DeploymentCleanupPhase.CLEANING_RESOURCES
                        else:
                            phase = DeploymentCleanupPhase.VERIFYING
                        
                        self.tracker.update_deployment(
                            self.dep_key,
                            phase=phase,
                            progress=progress_pct
                        )
                        self.live.update(self.tracker.create_progress_display())
                        
                        if self.step_count >= self.total_steps:
                            self.finished = True
                
                simple_progress = SimpleProgress(tracker, dep_key, live)
                
                # Backup CR before deletion
                tracker.update_deployment(
                    dep_key,
                    phase=DeploymentCleanupPhase.PREPARING,
                    step="Backing up Custom Resource",
                    progress=15
                )
                live.update(tracker.create_progress_display())
                
                try:
                    backup_path = backup_cr_before_deletion(
                        cr_data=dep_info["cr_data"],
                        cr_name=dep_info["cr_name"],
                        cr_type=dep_info["type"],
                        namespace=namespace,
                        logger=state["logger"]
                    )
                    state["logger"].info(f"CR backed up to: {backup_path}")
                except Exception as e:
                    state["logger"].warning(f"Failed to backup CR (continuing with cleanup): {e}")

                # ── Helm uninstall (if operator was installed via Helm) ───────
                # Run this before deleting the CR so the Helm release is gone
                # and re-deployment won't fail with "release already exists".
                helm_releases_to_check = [
                    "ibm-content-assistant-operator",
                    "ibm-usage-metering",
                ]
                for helm_release in helm_releases_to_check:
                    try:
                        check_result = subprocess.run(
                            ["helm", "list", "-n", namespace, "-o", "json"],
                            capture_output=True, text=True, check=False
                        )
                        if check_result.returncode == 0:
                            import json as _json
                            releases = _json.loads(check_result.stdout or "[]")
                            if any(r.get("name") == helm_release for r in releases):
                                tracker.update_deployment(
                                    dep_key,
                                    phase=DeploymentCleanupPhase.PREPARING,
                                    step=f"Uninstalling Helm: {helm_release}",
                                    progress=18
                                )
                                live.update(tracker.create_progress_display())
                                state["logger"].info(f"Uninstalling Helm release: {helm_release}")
                                result = subprocess.run(
                                    ["helm", "uninstall", helm_release, "-n", namespace],
                                    capture_output=True, text=True, check=False
                                )
                                if result.returncode != 0:
                                    state["logger"].warning(
                                        f"helm uninstall {helm_release} failed, retrying with --no-hooks: {result.stderr}"
                                    )
                                    result = subprocess.run(
                                        ["helm", "uninstall", helm_release, "-n", namespace,
                                         "--no-hooks", "--wait=false"],
                                        capture_output=True, text=True, check=False
                                    )
                                if result.returncode == 0:
                                    state["logger"].info(f"Helm release '{helm_release}' uninstalled successfully")
                                else:
                                    state["logger"].warning(
                                        f"helm uninstall '{helm_release}' failed (continuing): {result.stderr}"
                                    )
                    except Exception as helm_e:
                        state["logger"].warning(f"Helm uninstall check failed for '{helm_release}' (continuing): {helm_e}")

                # Update to deleting phase
                tracker.update_deployment(
                    dep_key,
                    phase=DeploymentCleanupPhase.DELETING_CR,
                    step="Deleting Custom Resource",
                    progress=20
                )
                live.update(tracker.create_progress_display())

                # Make the CR data available to delete_CR so it has full context.
                # The deployment subcommand fetches the CR into dep_info["cr_data"] but
                # does not call collect_cr_details(), so _cr_details is empty otherwise.
                state["clean"]._cr_details = dep_info.get("cr_data") or {}

                # Perform cleanup using enhanced delete_CR method
                task_id = 1  # Dummy task ID for compatibility
                while not simple_progress.finished:
                    state["clean"].delete_CR(
                        task_id,
                        simple_progress,
                        cr_type=dep_info["type"],
                        group=dep_info["group"],
                        version=dep_info.get("api_version", "v1"),
                        plural=dep_info["plural"],
                        cr_name=dep_info["cr_name"]
                    )
                
                # Mark as complete
                tracker.complete_deployment(dep_key, success=True)
                live.update(tracker.create_progress_display())
                return True

            except Exception as e:
                error_msg = f"Cleanup failed: {str(e)}"
                state["logger"].error(f"Error cleaning {dep_key}: {error_msg}")
                tracker.complete_deployment(dep_key, success=False, error=error_msg)
                live.update(tracker.create_progress_display())
                return False

        def cleanup_um_deployment(dep_key: str) -> bool:
            """Clean up a Usage Metering deployment CR via the box tracker."""
            try:
                dep_info = deployments_to_clean[dep_key]

                tracker.update_deployment(
                    dep_key,
                    phase=DeploymentCleanupPhase.DELETING_CR,
                    step="Deleting Usage Metering CR",
                    progress=20,
                )
                live.update(tracker.create_progress_display())

                state['logger'].info("Deleting Usage Metering CR")
                try:
                    state["clean"]._kube._custom_api.delete_namespaced_custom_object(
                        group=dep_info["group"],
                        version=dep_info["api_version"],
                        namespace=namespace,
                        plural=dep_info["plural"],
                        name=dep_info["cr_name"],
                    )
                    state['logger'].info(f"Deleted Usage Metering CR: {dep_info['cr_name']}")
                except Exception as e:
                    state['logger'].info(f"Error deleting Usage Metering CR: {e}")

                tracker.update_deployment(
                    dep_key,
                    phase=DeploymentCleanupPhase.VERIFYING,
                    step="Waiting for pods to terminate",
                    progress=60,
                )
                live.update(tracker.create_progress_display())

                state['logger'].info("Waiting for Usage Metering pods to terminate")
                # Poll every 5 seconds but tick live.update() every second so the
                # elapsed timer stays live instead of freezing during each sleep.
                POLL_INTERVAL = 5
                MAX_RETRIES = 20
                retries = 0
                while retries < MAX_RETRIES:
                    pods = state["clean"]._core_v1_api.list_namespaced_pod(
                        namespace,
                        label_selector="app.kubernetes.io/name=ibm-usage-metering"
                    )
                    if not pods.items:
                        break
                    retries += 1
                    for _ in range(POLL_INTERVAL):
                        time.sleep(1)
                        live.update(tracker.create_progress_display())

                tracker.update_deployment(dep_key, step="")
                tracker.complete_deployment(dep_key, success=True)
                live.update(tracker.create_progress_display())
                return True

            except Exception as e:
                error_msg = f"Usage Metering cleanup failed: {str(e)}"
                state["logger"].error(error_msg)
                tracker.complete_deployment(dep_key, success=False, error=error_msg)
                live.update(tracker.create_progress_display())
                return False

        # Clean deployments sequentially (safer for CRs), routing UM entries
        # through the dedicated cleaner so they appear in the same box UI.
        all_success = True
        for dep_key in selected_deployments:
            tracker.start_deployment(dep_key)
            if deployments_to_clean[dep_key]["type"] == "Usage Metering":
                success = cleanup_um_deployment(dep_key)
            else:
                success = cleanup_single_deployment(dep_key)
            if not success:
                all_success = False

        # Stop live display
        live.stop()

        # Mark overall completion
        tracker.overall_end_time = tracker.overall_start_time.__class__.now()

        # Display completion summary
        display_deployment_cleanup_complete(tracker, console)
        
    except KeyboardInterrupt:
        state["logger"].warning("Cleanup interrupted by user (Ctrl+C)")
        console.print()
        console.print(Panel.fit(
            "⚠️  Cleanup interrupted by user\n\n"
            "Cleaning up resources and shutting down gracefully...",
            title="[bold yellow]Keyboard Interrupt[/bold yellow]",
            border_style="yellow"
        ))
        
        # Stop live display
        if live._started:
            live.stop()
        
        # Mark incomplete deployments as failed
        for dep_key in selected_deployments:
            if not tracker.statuses[dep_key].is_complete:
                tracker.complete_deployment(
                    dep_key,
                    success=False,
                    error="Interrupted by user"
                )
        
        # Display partial results
        console.print()
        console.print(Panel.fit(
            "Cleanup was interrupted. Some deployments may have been partially cleaned.",
            title="[bold yellow]⚠️  Partial Cleanup[/bold yellow]",
            border_style="yellow"
        ))
        
        exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context,
         version: Annotated[bool, typer.Option(
             "--version", help="Show version and exit.",
             callback=version_callback, is_eager=True)] = False,
         silent: Annotated[bool, typer.Option(
             help="Enable Silent Install (no prompts).",
             rich_help_panel="Customization and Utils")] = False,
         verbose: Annotated[bool, typer.Option(
             help="Enable verbose logging.",
             rich_help_panel="Customization and Utils")] = False,
         dryrun: Annotated[bool, typer.Option(
             help="Perform a dry run",
             rich_help_panel="Customization and Utils")] = False):
    """
        IBM Content Assistant Deployment Cleanup CLI.
    """
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if dryrun:
        state["dryrun"] = True

    if ctx.invoked_subcommand is None:
        display_mode_version("Deployment and Operator Cleanup",
                             "Clean up of the IBM Content Assistant Deployment and IBM Content Assistant Operator")
        state['logger'].info(f"Cleaning up of both the IBM Content Assistant Deployment and IBM Content Assistant Operator")
        
        # Display what will be cleaned
        info_text = Text()
        info_text.append("This mode will remove:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("IBM Content Assistant Custom Resource (CR)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("All deployed workloads and services\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("IBM Content Assistant Operator and Deployment\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Operator RBAC resources (Role, RoleBinding, ServiceAccount)\n", style="white")
        
        print(Panel(
            info_text,
            title="[bold white]🧹 Cleanup Scope[/bold white]",
            border_style="yellow",
            padding=(1, 2)
        ))
        print()

    elif ctx.invoked_subcommand == "operator":
        display_mode_version("Operator Cleanup", "Clean up of the IBM Content Assistant Operator Only")
        state['logger'].info(f"Cleaning up of the IBM Content Assistant Operator Only")
        
        # Display what will be cleaned
        info_text = Text()
        info_text.append("This mode will remove:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("IBM Content Assistant Operator and Deployment\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("Operator RBAC resources (Role, RoleBinding, ServiceAccount)\n", style="white")
        info_text.append("  ⚠️  ", style="bold yellow")
        info_text.append("Deployments will remain (manual cleanup required)\n", style="yellow")
        
        print(Panel(
            info_text,
            title="[bold white]🧹 Cleanup Scope[/bold white]",
            border_style="yellow",
            padding=(1, 2)
        ))
        print()

    elif ctx.invoked_subcommand == "deployment":
        display_mode_version("Deployment Cleanup", "Clean up of the IBM Content Assistant Deployment Only")
        state['logger'].info(f"Cleaning up of the IBM Content Assistant Deployment Only")
        
        # Display what will be cleaned
        info_text = Text()
        info_text.append("This mode will remove:\n\n", style="bold white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("IBM Content Assistant Custom Resource (CR)\n", style="white")
        info_text.append("  ✓ ", style="bold green")
        info_text.append("All deployed workloads and services\n", style="white")
        info_text.append("  ⚠️  ", style="bold yellow")
        info_text.append("Operator will remain (manual cleanup required)\n", style="yellow")
        
        print(Panel(
            info_text,
            title="[bold white]🧹 Cleanup Scope[/bold white]",
            border_style="yellow",
            padding=(1, 2)
        ))
        print()

    checks = ["connection"]
    missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks)

    # Print table of prerequisites that are missing
    if len(missing_tools) > 0 or len(files) > 0:
        layout = display_issues(tools=missing_tools, descriptors=files)
        print(layout)
        exit(1)
    else:
        display_prereq_validation_table(results)

    # Read Version File
    state['logger'].info(f"Reading version details")
    version_path = os.path.join(os.path.dirname(os.getcwd()), "version.toml")
    if not os.path.exists(version_path):
        version_path = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), "version.toml")

    if os.path.exists(version_path):
        state["version_data"] = read_version_toml(version_path, state["logger"])
    else:
        state["version_data"] = {}

    if silent:
        state["silent"] = True
        silent_path = os.path.join("silent_config", "silent_install_cleandeployment.toml")

        # Validate configuration with Pydantic before proceeding
        state["logger"].info(f"Validating silent clean-deployment configuration: {silent_path}")
        try:
            import toml as _toml
            with open(silent_path, 'r') as _f:
                _config_dict = _toml.load(_f)
            _success, _, _validation_errors = validate_cleandeployment_config(_config_dict)
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

        state["setup"] = sg.SilentGatherOptions(state["logger"], silent_path, script_type="cleanup")
        state["setup"].podman_available = results["podman"]
        state["setup"].silent_namespace()

    else:
        state["setup"] = g.GatherOptions(state["logger"], console, script_type="cleanup")
        state["setup"].podman_available = results["podman"]
        state['logger'].info(f"Collecting namespace")
        state["setup"].collect_namespace()

    state["clean"] = dc.CleanDeployment(console, state["setup"], state["logger"], silent=state["silent"])
    state["version_details"] = create_version_info(state["setup"], state["version_data"])

    if ctx.invoked_subcommand is None:
        deployment_dict, resource_dict = state["clean"].collect_cr_details()
        operator_dict = state["clean"].collect_operator_details()

        if not operator_dict and not deployment_dict:
            print()
            print(Panel.fit(
                f"No IBM Content Assistant deployments or operators found in namespace: {state['clean']._deployment_prerequisites.namespace}",
                border_style="yellow"))
            namespace = state["clean"]._deployment_prerequisites.namespace
            state['logger'].info(f"IBM Content Assistant Operator or Deployment is not found in the namespace: {namespace}")
            exit(1)
        cleanup_summary = display_deployment_resources(logger=state['logger'],
                                                       deployment_resources=resource_dict,
                                                       deployment_details=deployment_dict,
                                                       operator_details=operator_dict,
                                                       version_details=state["version_details"])

        print()
        print()
        print(cleanup_summary)

        # Get usage metering details and status upfront
        namespace = state["clean"]._deployment_prerequisites.namespace
        um_details = getattr(state["clean"], "_usage_metering_details", {})
        delete_um_deployment = False
        delete_um_operator = False
        um_cr_list = []
        um_cr_exists = False

        if um_details:
            try:
                um_cr_list = state["clean"]._kube._custom_api.list_namespaced_custom_object(
                    group="operator.ibm.com", version="v1",
                    namespace=namespace, plural="ibmusagemeterings"
                ).get("items", [])
                um_cr_exists = bool(um_cr_list)
            except Exception:
                um_cr_exists = False
                um_cr_list = []

        # Ask to delete CR from deployment only for non silent mode
        if not state["silent"]:
            print()
            if operator_dict and deployment_dict:
                msg = "Do you want to proceed and cleanup the above IBM Content Assistant Deployment and Operator?"
            elif operator_dict:
                msg = "Do you want to proceed and cleanup the above IBM Content Assistant Operator?"
            else:
                msg = "Do you want to proceed and cleanup the above IBM Content Assistant Deployment?"
            
            clean_deployment = questionary.confirm(
                msg,
                default=False,
                style=questionary.Style([
                    ('question', 'bold'),
                    ('answer', 'fg:green bold'),
                ])
            ).ask()
            
            if clean_deployment is None:  # User pressed Ctrl+C
                print("\n[yellow]⚠️  Cleanup cancelled by user[/yellow]")
                exit(0)

            # Combine other prompts upfront immediately after the main prompt
            if clean_deployment and um_details:
                print()
                if um_cr_exists:
                    print("[yellow]⚠[/yellow]  Usage Metering operator and deployment detected.")
                    print("  It may be shared with other deployments.")
                    print()
                    delete_um_deployment = questionary.confirm(
                        "Do you want to also delete the Usage Metering deployment (CR + workloads)?",
                        default=False,
                        style=questionary.Style([('question', 'bold'), ('answer', 'fg:green bold')])
                    ).ask()
                    if delete_um_deployment is None:
                        delete_um_deployment = False
                else:
                    print("[yellow]⚠[/yellow]  Usage Metering operator detected (deployment already removed).")
                    print("  The operator pod is still running.")
                    print()

                if delete_um_deployment or not um_cr_exists:
                    print()
                    delete_um_operator = questionary.confirm(
                        "Do you also want to delete the Usage Metering operator?",
                        default=False,
                        style=questionary.Style([('question', 'bold'), ('answer', 'fg:green bold')])
                    ).ask()
                    if delete_um_operator is None:
                        delete_um_operator = False

                if not delete_um_deployment and um_cr_exists:
                    state['logger'].info("User chose to keep Usage Metering deployment — skipping UM CR cleanup")
        else:
            clean_deployment = True
            # Silent mode
            if um_details:
                cleanup_um = getattr(state["setup"], "cleanup_usage_metering", False)
                if cleanup_um:
                    delete_um_deployment = um_cr_exists
                    delete_um_operator = True
                    state['logger'].info("Silent mode: Cleaning up Usage Metering deployment and operator as requested")
                else:
                    delete_um_deployment = False
                    delete_um_operator = False
                    state['logger'].info("Silent mode: Keeping Usage Metering — CLEANUP_USAGE_METERING is false")

        # Dry run flow ends here
        if state["dryrun"]:
            print()
            print(Panel.fit(
                "🔍 Dry run completed - no resources were deleted",
                border_style="green"
            ))
            exit()

        if clean_deployment:
            # Set values on state["clean"] before clearing console and beginning cleanup
            state["clean"]._delete_um_deployment = delete_um_deployment
            state["clean"]._delete_um_operator = delete_um_operator
            if not delete_um_deployment and not delete_um_operator:
                state["clean"]._usage_metering_details = {}
                um_details = {}

            # Now clear the console ONCE at the start of actual execution!
            clear(console)

            import threading as _threading
            from helper_scripts.utilities.cleanup_progress import (
                DeploymentCleanupTracker,
                DeploymentCleanupPhase,
                MultiOperatorCleanupTracker,
                CleanupPhase,
                DynamicRenderable,
            )

            def _make_dep_simple_progress(tracker, dep_key, live):
                """Shim adapting delete_CR()/delete_operator() advance/log to the box tracker."""
                class _Shim:
                    def __init__(self, total):
                        self.finished = False
                        self._step = 0
                        self._total = total

                    def log(self, message=""):
                        msg = str(message).strip()
                        if msg and not msg.startswith("\n"):
                            tracker.update_deployment(dep_key, step=msg[:50])
                            live.update(tracker.create_progress_display())

                    def advance(self, task_id):
                        self._step += 1
                        pct = int(self._step / self._total * 90) + 10
                        if pct < 30:
                            phase = DeploymentCleanupPhase.DELETING_CR
                        elif pct < 80:
                            phase = DeploymentCleanupPhase.CLEANING_RESOURCES
                        else:
                            phase = DeploymentCleanupPhase.VERIFYING
                        tracker.update_deployment(dep_key, phase=phase, progress=pct)
                        live.update(tracker.create_progress_display())
                        if self._step >= self._total:
                            self.finished = True
                return _Shim(8)

            def _make_op_simple_progress(tracker, live, task_mappings: dict):
                """Shim adapting delete_operator() advance/log to the box tracker with dynamic task mappings."""
                class _Shim:
                    def __init__(self):
                        self.finished = False
                        self._steps = {tid: 0 for tid in task_mappings}
                        self._totals = {tid: limit for tid, (_, limit) in task_mappings.items()}

                    def log(self, message=""):
                        msg = str(message).strip()
                        if msg and not msg.startswith("\n"):
                            first_op = list(task_mappings.values())[0][0]
                            tracker.update_operator(first_op, phase=CleanupPhase.CLEANING)
                            live.update(tracker.create_progress_display())

                    def start(self, task_id):
                        if task_id in task_mappings:
                            op_key, _ = task_mappings[task_id]
                            tracker.start_operator(op_key)
                            live.update(tracker.create_progress_display())

                    def advance(self, task_id):
                        if task_id in task_mappings:
                            op_key, total = task_mappings[task_id]
                            self._steps[task_id] += 1
                            pct = int(self._steps[task_id] / total * 90) + 10
                            tracker.update_operator(op_key, phase=CleanupPhase.CLEANING, progress=pct)
                            live.update(tracker.create_progress_display())
                            # We are finished when the primary task completes (either task 1, or task 2 if task 1 is not mapped)
                            primary_task_id = 1 if 1 in task_mappings else 2
                            if task_id == primary_task_id and self._steps[task_id] >= total:
                                self.finished = True
                return _Shim()

            def _run_in_thread_with_live(fn, live, tracker):
                """Run fn() in a daemon thread; tick live.update() every second until done."""
                _done = _threading.Event()
                def _worker():
                    fn()
                    _done.set()
                _threading.Thread(target=_worker, daemon=True).start()
                while not _done.wait(timeout=1):
                    if live and live._started:
                        live.update(tracker.create_progress_display())

            # Build unified deployments dictionary from the start
            deployments_to_track = {}
            if deployment_dict:
                _dep_cr_name = deployment_dict.get("Name", "casdeploy")
                _dep_version = deployment_dict.get("Version", "Unknown")
                deployments_to_track["content-assistant"] = {
                    "type": "Content Assistant",
                    "cr_name": _dep_cr_name,
                    "version": _dep_version,
                }
            if delete_um_deployment:
                _um_cr_name = (um_cr_list[0].get("metadata", {}).get("name", "ibmusagemetering")
                               if um_cr_list else "ibmusagemetering")
                deployments_to_track["usage-metering"] = {
                    "type": "Usage Metering",
                    "cr_name": _um_cr_name,
                    "version": "—",
                }

            _p1_tracker = DeploymentCleanupTracker(
                deployments=deployments_to_track,
                console=console,
            )

            # Start Live display ONCE for all deployment cleanup
            _p1_live = None
            if deployments_to_track:
                state['logger'].info("Starting Deployments Cleanup (unified tracker)")
                _p1_live = Live(DynamicRenderable(_p1_tracker.create_progress_display),
                                console=console, refresh_per_second=4, transient=False)
                _p1_live.start()

            # ── Phase 1: Clean CAS Deployment (CR + workloads) ───────────────
            if deployment_dict:
                state['logger'].info("Phase 1: Starting IBM Content Assistant Deployment Cleanup")
                _p1_tracker.start_deployment("content-assistant")
                _dep_progress = _make_dep_simple_progress(_p1_tracker, "content-assistant", _p1_live)
                task_dep = 1

                def _do_delete_cr():
                    while not _dep_progress.finished:
                        state["clean"].delete_CR(task_dep, _dep_progress)

                _run_in_thread_with_live(_do_delete_cr, _p1_live, _p1_tracker)
                _p1_tracker.update_deployment("content-assistant", step="")
                _p1_tracker.complete_deployment("content-assistant", success=True)
                if _p1_live and _p1_live._started:
                    _p1_live.update(_p1_tracker.create_progress_display())

            # ── Phase 1b: Clean UM Deployment (CR + workloads) ───────────────
            if delete_um_deployment:
                state['logger'].info("Phase 1b: Starting Usage Metering Deployment Cleanup")
                _p1_tracker.start_deployment("usage-metering")
                _p1_tracker.update_deployment(
                    "usage-metering",
                    phase=DeploymentCleanupPhase.DELETING_CR,
                    step="Deleting Usage Metering CR",
                    progress=20,
                )
                if _p1_live and _p1_live._started:
                    _p1_live.update(_p1_tracker.create_progress_display())

                try:
                    state["clean"]._kube._custom_api.delete_namespaced_custom_object(
                        group="operator.ibm.com", version="v1",
                        namespace=namespace, plural="ibmusagemeterings", name=_um_cr_name)
                    state['logger'].info(f"Deleted Usage Metering CR: {_um_cr_name}")
                except Exception as e:
                    state['logger'].info(f"Error deleting Usage Metering CR: {e}")

                _p1_tracker.update_deployment(
                    "usage-metering",
                    phase=DeploymentCleanupPhase.VERIFYING,
                    step="Waiting for pods to terminate",
                    progress=60,
                )
                if _p1_live and _p1_live._started:
                    _p1_live.update(_p1_tracker.create_progress_display())

                def _wait_um_pods():
                    retries = 0
                    while retries < 20:
                        pods = state["clean"]._core_v1_api.list_namespaced_pod(
                            namespace,
                            label_selector="app.kubernetes.io/name=ibm-usage-metering"
                        )
                        if not pods.items:
                            break
                        retries += 1
                        for _ in range(5):
                            time.sleep(1)
                            if _p1_live and _p1_live._started:
                                _p1_live.update(_p1_tracker.create_progress_display())

                _run_in_thread_with_live(_wait_um_pods, _p1_live, _p1_tracker)
                _p1_tracker.update_deployment("usage-metering", step="")
                _p1_tracker.complete_deployment("usage-metering", success=True)
                if _p1_live and _p1_live._started:
                    _p1_live.update(_p1_tracker.create_progress_display())

            # Stop Live panel once both deployments are fully processed
            if _p1_live and _p1_live._started:
                _p1_live.stop()

            # ── Phase 2: Clean Operator(s) ────────────────────────────────────
            if operator_dict or (um_details and delete_um_operator):
                operator_task_num = 5  # Default for YAML-based
                if operator_dict:
                    if operator_dict.get("type") == "OLM":
                        operator_task_num = 4
                    elif operator_dict.get("type") == "HELM":
                        operator_task_num = 2

                state['logger'].info("Phase 2: Starting Operator Cleanup")
                _op_entries = {}
                if operator_dict:
                    _op_entries["content-assistant"] = {"type": operator_dict.get("type", "HELM")}
                if um_details and delete_um_operator:
                    _op_entries["usage-metering"] = {"type": um_details.get("type", "HELM")}

                _p2_tracker = MultiOperatorCleanupTracker(operators=_op_entries, console=console)
                _p2_live = Live(DynamicRenderable(_p2_tracker.create_progress_display),
                                console=console, refresh_per_second=4, transient=False)
                _p2_live.start()

                um_task_num = 1
                task_op = 1 if operator_dict else None
                task_um = 2 if (um_details and delete_um_operator) else None

                if task_um is not None:
                    _um_type = um_details.get("type", "YAML")
                    if _um_type == "OLM":
                        um_task_num = 5
                    elif _um_type == "HELM":
                        um_task_num = 3
                    else:
                        um_task_num = 3

                # Build task mappings for progress shimming
                _mappings = {}
                if task_op is not None:
                    _mappings[task_op] = ("content-assistant", operator_task_num)
                if task_um is not None:
                    _mappings[task_um] = ("usage-metering", um_task_num)

                _op_progress = _make_op_simple_progress(_p2_tracker, _p2_live, _mappings)

                def _do_delete_operator():
                    while not _op_progress.finished:
                        state["clean"].delete_operator(task_op, _op_progress,
                                                       delete_um_operator=delete_um_operator,
                                                       task_um=task_um)

                _run_in_thread_with_live(_do_delete_operator, _p2_live, _p2_tracker)
                if operator_dict:
                    _p2_tracker.complete_operator("content-assistant", success=True)
                if um_details and delete_um_operator:
                    _p2_tracker.complete_operator("usage-metering", success=True)
                _p2_live.update(_p2_tracker.create_progress_display())
                _p2_live.stop()
            # Display completion summary
            display_cleanup_completion(
                operator_cleaned=bool(operator_dict),
                deployment_cleaned=bool(deployment_dict),
                operator_type=operator_dict.get("type") if operator_dict else None,
                namespace=namespace,
                um_deployment_cleaned=delete_um_deployment,
                um_operator_cleaned=delete_um_operator,
            )


if __name__ == "__main__":
    app()
