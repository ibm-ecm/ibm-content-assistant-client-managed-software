###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################


# Write a main function that parses command line arguments
#  - the main should take a mode as an argument
#  - the modes can are gather, generate, validate
#  - the gather mode accepts a migration option
#  - the migration option accept a folder location
#  - the main should call the appropriate function based on the mode
#  - the main should pass the parsed arguments to the function
#  - the main should print the output of the function

import logging
import os
import re
import shutil
import sys
import toml
from datetime import datetime
from pathlib import Path
from typing import Optional
from typing_extensions import Annotated

import typer
import questionary
from questionary import Style
from rich import print
from rich.columns import Columns
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from toml.decoder import TomlDecodeError

from helper_scripts.gather import gather_prerequisites as g
from helper_scripts.gather import silent_gather_prerequisites as sg
from helper_scripts.generate.generate_cas_readme import GenerateCASReadme
from helper_scripts.generate.generate_configmaps import GenerateConfigMaps
from helper_scripts.generate.generate_cr import GenerateCR
from helper_scripts.generate.generate_metrics import GenerateMetrics
from helper_scripts.generate.generate_secrets import GenerateSecrets
from helper_scripts.property import property as p
from helper_scripts.property.read_prop import *
from helper_scripts.property.generate_property_readme import GeneratePropertyReadme
from helper_scripts.utilities.interface import clear, generate_gather_results, generate_generate_results, \
    display_issues, display_prereq_validation_table
from helper_scripts.utilities.questionary_utils import safe_questionary_prompt
from helper_scripts.utilities.prerequisites_utilites import zip_folder, \
    create_generate_folder, check_ssl_folders_cas, check_trusted_certs
from helper_scripts.utilities.utilities import read_version_toml, prereq_checks
from helper_scripts.validate import validate as v
from helper_scripts.validate.validation_display import ValidationDisplay, DisplayProgressAdapter


def _read_product_version() -> str:
    """Read VERSION from version.toml for the CLI header and --version flag."""
    try:
        _toml_path = Path(__file__).parent.parent / "version.toml"
        _data = toml.loads(_toml_path.read_text(encoding="utf-8"))
        return _data.get("VERSION", "26.0.0").split("-")[0]
    except Exception:
        return "26.0.0"

__version__ = "1.4.0"


app = typer.Typer()
state = {
    "verbose": False,
    "silent": False,
    "logger": logging
}

console = Console(record=True)


def version_callback(value: bool):
    if value:
        print(f"IBM Content Assistant Deployment Prerequisites -- CLI: {__version__}")
        raise typer.Exit()


@app.callback()
def main(ctx: typer.Context,
         version: Annotated[bool, typer.Option(
             "--version", help="Show version and exit.",
             callback=version_callback, is_eager=True)] = None,
         silent: Annotated[bool, typer.Option(
             help="Enable Silent Install (no prompts).",
             rich_help_panel="Customization and Utils")] = False,
         verbose: Annotated[bool, typer.Option(
             help="Enable verbose logging.",
             rich_help_panel="Customization and Utils")] = False):

    """
    IBM Content Assistant Deployment Prerequisites -- CLI.
    """
    if verbose:
        state["verbose"] = True
        FILE_LOG_LEVEL = logging.DEBUG
    else:
        FILE_LOG_LEVEL = logging.WARNING

    state["logger"] = setup_logger(FILE_LOG_LEVEL)

    if silent:
        state["silent"] = True

    # Read Version File
    version_path = os.path.join(os.path.dirname(os.getcwd()), "version.toml")
    if not os.path.exists(version_path):
        version_path = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), "version.toml")

    if os.path.exists(version_path):
        state["version_data"] = read_version_toml(version_path, state["logger"])
    else:
        state["version_data"] = {}

    # Only run prerequisite checks if a subcommand is invoked AND --help is not in arguments
    # This prevents checks from running when --help or --version is used
    if ctx.invoked_subcommand is not None and "--help" not in sys.argv:
        if ctx.invoked_subcommand == "gather":
            if not state["silent"]:
                clear(console)
            display_mode_version("Gather",
                                 "Gather information required for IBM Content Assistant Deployment")
            checks = ["connection"]
            files = []

        elif ctx.invoked_subcommand == "generate":
            display_mode_version("Generate",
                                 "Generate all deployment YAMLs and Secrets for IBM Content Assistant Deployment")
            checks = ["connection"]
            files = []

        elif ctx.invoked_subcommand == "validate":
            display_mode_version("Validate",
                                 "Validate all prerequisites for IBM Content Assistant Deployment")
            checks = ["connection"]
            files = []

        missing_tools, results, files = prereq_checks(logger=state["logger"], prereqs=checks, files=files)

        # Print table of prerequisites that are missing
        if len(missing_tools) > 0 or len(files) > 0:
            state["logger"].info("Prerequisites failed. Displaying missing tools and files.")
            layout = display_issues(tools=missing_tools, descriptors=files)
            print(layout)
            exit(1)
        else:
            state["logger"].info("Prerequisites passed.")
            display_prereq_validation_table(results)


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
    file_handler = logging.FileHandler("prerequisites.log")
    file_handler.setLevel(logging.DEBUG)
    formatter_file = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)-100s - %(filename)s:%(lineno)d", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(formatter_file)

    # Add handlers to the logger
    logger.addHandler(shell_handler)
    logger.addHandler(file_handler)

    return logger


# ── Icon constants ────────────────────────────────────────────────────────────
_MODE_ICONS = {
    "Gather": "📝",
    "Generate": "🔧",
    "Validate": "✔",
}

_STATUS_ICONS = {
    "success": "[bold green]✓[/bold green]",
    "skip": "[bold yellow]⊘[/bold yellow]",
    "error": "[bold red]✗[/bold red]",
    "warn": "[bold yellow]⚠[/bold yellow]",
    "info": "[bold cyan]ℹ[/bold cyan]",
}


def display_mode_version(mode: str, description: str) -> None:
    """
    Display the mode and version of the script with active flags in a modern, visually appealing format.

    Args:
        mode:        Operation mode — "Gather", "Generate", or "Validate".
        description: One-line description of what the mode does.
    """
    if not state["silent"]:
        clear(console)

    icon = _MODE_ICONS.get(mode, "▶")

    # Create header table with version and mode info
    header_table = Table.grid(padding=(0, 2))
    header_table.add_column(style="cyan", justify="left")
    header_table.add_column(style="white", justify="left")

    # Add version and mode rows
    header_table.add_row("Version:", f"[bold green]{__version__}[/bold green]")
    header_table.add_row("Mode:", f"[bold yellow]{icon}  {mode}[/bold yellow]")
    header_table.add_row("", f"[dim]{description}[/dim]")

    # Collect active flags
    active_flags = []
    if state["silent"]:
        active_flags.append("🤫 Silent Mode")
        state["logger"].info("Silent Mode is enabled")

    if state["verbose"]:
        active_flags.append("📢 Verbose Logging")
        state["logger"].info("Verbose Logging is enabled")

    # Add active flags if any
    if active_flags:
        header_table.add_row("", "")  # Empty row for spacing
        for flag in active_flags:
            header_table.add_row("", f"[bold magenta]{flag}[/bold magenta]")

    # Log script details
    log_msg = f"Version: {__version__}\nMode: {mode}\n{description}"
    if active_flags:
        log_msg += "\n\n" + "\n".join(active_flags)
    state["logger"].info(f"Script details: \n{log_msg}")

    print()
    print(Panel(
        header_table,
        title="[bold white]📋 IBM Content Assistant Prerequisites CLI[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
        expand=False,
    ))
    print()


def _scope_table(items: list[tuple[str, bool]]) -> Table:
    """
    Build a two-column Table.grid showing scope items with check/skip icons.

    Args:
        items: List of (label, included) tuples.  included=True → green ✓,
               included=False → yellow ⊘ (skipped).

    Returns:
        A Table.grid ready to embed in a Panel.
    """
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(width=3)
    tbl.add_column(style="white")
    for label, included in items:
        icon = _STATUS_ICONS["success"] if included else _STATUS_ICONS["skip"]
        suffix = "" if included else " [dim](skipped)[/dim]"
        tbl.add_row(icon, f"{label}{suffix}")
    return tbl


def _mode_scope_panel(scope_items: list[tuple[str, bool]], title: str = "Scope") -> Panel:
    """Wrap a scope table in a consistently styled cyan Panel."""
    return Panel(
        _scope_table(scope_items),
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )


@app.command()
def gather():
    """
    Gather the prerequisites for IBM Content Assistant Deployment.
    """

    if not state["silent"]:
        scope_items = [
            ("License model and platform selection", True),
            ("Namespace for deployment", True),
            ("Platform and ingress configuration", True),
            ("AI provider type and settings", True),
            ("Vector database connection details", True),
            ("Network policy configuration", True),
        ]
        print()
        print(_mode_scope_panel(scope_items, title="📝  Gather — Configuration Collection"))
        print()

        # this is the user details object
        gather = g.GatherPrereqOptions(state["logger"], console)

        gather.collect_license_model(state["version_data"])
        clear(console)

        gather.collect_namespace()
        clear(console)

        clear(console)
        gather.collect_platform_ingress()

        clear(console)
        gather.collect_ai_provider_type()
        if gather.ai_provider_type == "MODEL_GATEWAY":
            clear(console)
            gather.collect_model_gateway_details()

        # Only offer OpenSearch cluster creation for CP4BA license
        if gather.license_model and gather.license_model.upper().startswith("CP4BA"):
            clear(console)
            gather.collect_opensearch_cluster_option()

        # Only collect vector database details if not using OpenSearch
        if not gather.create_opensearch_cluster:
            clear(console)
            gather.collect_vector_db_details()

        clear(console)
        gather.collect_fips_support()

        clear(console)
        gather.collect_networkpolicy_info()

        clear(console)

    else:
        # add logic to populate details using silent mode

        # below line is for custom silent install config file
        gather = sg.SilentGatherPrereqOptions(state["logger"],
                                              os.path.join("silent_config", "silent_install_prerequisites.toml"))

        # Individual components loaded:
        gather.silent_version(state["version_data"])
        gather.silent_namespace()
        gather.silent_platform()
        gather.silent_fips_support()
        gather.silent_network_policies_support()
        gather.silent_license_model()
        gather.silent_ai_provider_type()
        if gather.ai_provider_type == "MODEL_GATEWAY":
            gather.silent_model_gateway_details()
        # Only load OpenSearch cluster flag for CP4BA license
        if gather.license_model and gather.license_model.upper().startswith("CP4BA"):
            gather.silent_opensearch_cluster()
        # Only collect vector database details if not using OpenSearch
        if not gather.create_opensearch_cluster:
            gather.silent_vector_db()
        gather.silent_ai_provider_count()
        gather.error_check()

    namespace = gather.namespace
    state["logger"].info(f"Namespace: {namespace}")

    # Zip up previous propertyFile if it exists
    # Remove the propertyFile folder
    if os.path.exists(os.path.join(os.getcwd(), "propertyFile", namespace)):
        if not os.path.exists(os.path.join(os.getcwd(), "backups")):
            os.mkdir(os.path.join(os.getcwd(), "backups"))
        now = datetime.now()
        dt_string = now.strftime("%Y-%m-%d_%H-%M")
        zip_folder(os.path.join(os.getcwd(), "backups", f"propertyFile_{namespace}_{dt_string}"),
                   os.path.join(os.getcwd(), "propertyFile", namespace))
        shutil.rmtree(os.path.join(os.getcwd(), "propertyFile", namespace))

    # function call to create property files
    property_obj = p.Property(gather, os.getcwd(), state["logger"], console)

    # create and populate the content assistant property and vector database property file
    # Note: populate methods must be called BEFORE create_property_structure
    # because they add SSL folder names to ssl_directory_list
    content_assistant_properties = property_obj.populate_content_assistant_details()

    # Always populate vector database properties
    # If OpenSearch is selected, it will be prefilled with OpenSearch details
    vector_database_properties = property_obj.populate_vector_database_details()

    # Now create the property structure with all SSL folders
    property_obj.create_property_structure()

    property_obj.create_content_assistant_propertyfile(content_assistant_properties)
    property_obj.create_vector_database_propertyfile(vector_database_properties)
    property_obj.create_deployment_propertyfile()
    if gather.ingress:
        property_obj.create_ingress_propertyfile()

    # Generate README documentation for property files
    try:
        state["logger"].info("Generating property file documentation")
        property_readme_generator = GeneratePropertyReadme(
            namespace=namespace,
            property_folder=property_obj.property_folder,
            gather_obj=gather,
            logger=state["logger"]
        )

        if property_readme_generator.generate_readme():
            state["logger"].info("✓ Property file README generated successfully")
            print(f"\n[green]✓ Property file documentation generated: propertyFile/{namespace}/README.md[/green]")
        else:
            state["logger"].warning("⚠ Property file README generation failed")
            print(f"\n[yellow]⚠ Property file README generation failed[/yellow]")
    except Exception as e:
        state["logger"].error(f"Error generating property file README: {str(e)}")
        print(f"\n[yellow]⚠ Error generating property file README: {str(e)}[/yellow]")

    clear(console)
    layout = generate_gather_results(property_obj.property_folder,
                                     gather.to_dict(), False, False)

    print(layout)


@app.command()
def generate():
    """
    Generate the prerequisites for IBM Content Assistant Deployment.
    """

    if not state["silent"]:
        scope_items = [
            ("Kubernetes Secrets — Content Assistant & Vector Database", True),
            ("SSL certificate secrets (if configured)", True),
            ("Custom Resource (CR) YAML file", True),
            ("Trusted certificate secrets (if configured)", True),
        ]
        print()
        print(_mode_scope_panel(scope_items, title="🔧  Generate — Kubernetes Artifacts"))
        print()

        # this is the user details object
        deploy1 = g.GatherPrereqOptions(state["logger"], console)
        deploy1.collect_namespace()
    else:
        deploy1 = sg.SilentGatherPrereqOptions(state["logger"],
                                               os.path.join("silent_config", "silent_install_prerequisites.toml"))
        # Individual components loaded:
        deploy1.silent_version(state["version_data"])
        deploy1.silent_namespace()

    namespace = deploy1.namespace
    state["logger"].info(f"Namespace: {namespace}")

    # Loading property folder locations
    prop_folder = os.path.join(os.getcwd(), "propertyFile", namespace)

    if not os.path.exists(prop_folder):
        state["logger"].info("Property files are missing. Please run the gather command first.")
        print()
        print(_missing_prop_panel(namespace))
        raise typer.Exit()

    ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
    trusted_certs_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "trusted-certs")

    # Loading generated folder location
    generated_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)

    # Loading property files locations
    content_assistant_prop_file = os.path.join(prop_folder, "cas_properties.toml")
    deployment_prop_file = os.path.join(prop_folder, "cas_deployment.toml")
    vector_database_prop_file = os.path.join(prop_folder, "cas_vector_database.toml")
    ingress_prop_file = os.path.join(prop_folder, "cas_ingress.toml")

    # Set defaults for property files
    deployment_prop = None
    ingress_prop = None
    content_assistant_prop = None
    vector_database_prop = None

    try:
        # Load property files if they exist
        if os.path.exists(content_assistant_prop_file):
            content_assistant_prop = ReadPropContentAssistant(content_assistant_prop_file, state["logger"])

        if os.path.exists(deployment_prop_file):
            deployment_prop = ReadPropDeployment(deployment_prop_file, state["logger"])

        if os.path.exists(vector_database_prop_file):
            vector_database_prop = ReadPropVectorDatabase(vector_database_prop_file, state["logger"])

        if os.path.exists(ingress_prop_file):
            ingress_prop = ReadPropIngress(ingress_prop_file, state["logger"])

        # Create dictionaries for property files if not None
        if vector_database_prop:
            vector_database_prop_dict = vector_database_prop.to_dict()
        else:
            vector_database_prop_dict = {}

        if content_assistant_prop:
            content_assistant_prop_dict = content_assistant_prop.to_dict()
        else:
            content_assistant_prop_dict = {}

        if deployment_prop:
            deployment_prop_dict = deployment_prop.to_dict()
        else:
            deployment_prop_dict = {}

        if ingress_prop:
            ingress_prop_dict = ingress_prop.to_dict()
        else:
            ingress_prop_dict = {}

    except TomlDecodeError:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)
    except Exception as e:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)

    # Check if SSL certificates are present and correct format
    missing_certs, incorrect_certs = check_ssl_folders_cas(content_assistant_prop=content_assistant_prop_dict,
                                                           vector_database_prop=vector_database_prop_dict,
                                                           ssl_cert_folder=ssl_cert_folder)

    trusted_certs_present, invalid_trusted_certs = check_trusted_certs(trusted_certs_folder)

    cert_failed = len(missing_certs) > 0 or len(incorrect_certs) > 0 or (
            trusted_certs_present and len(invalid_trusted_certs) > 0)

    # Validate OpenSearch password strength if using CP4BA OpenSearch
    password_validation_errors = {}
    if deployment_prop_dict.get("LICENSE", "").upper() == "CP4BA":
        for vector_database_id in vector_database_prop_dict.get("_vector_database_ids", []):
            database_url = vector_database_prop_dict.get(vector_database_id, {}).get("DATABASE_URL", "")
            if "ica-opensearch" in database_url:
                from helper_scripts.utilities.prerequisites_utilites import validate_opensearch_password
                password = vector_database_prop_dict.get(vector_database_id, {}).get("DATABASE_USER_PASSWORD", "")
                if password and password != "<Required>":
                    is_valid, error_msg = validate_opensearch_password(password)
                    if not is_valid:
                        password_validation_errors[vector_database_id] = error_msg
                        state["logger"].error(
                            f"OpenSearch password validation failed for {vector_database_id}: {error_msg}")

    # Collect missing fields from ALL property files
    required_fields = {}
    for prop_obj in (content_assistant_prop, deployment_prop, vector_database_prop, ingress_prop):
        if prop_obj is not None and prop_obj.missing_required_fields():
            required_fields.update(prop_obj.required_fields)

    any_missing = bool(required_fields)

    if any_missing or cert_failed or password_validation_errors:
        # Display OpenSearch password validation errors with rich formatting
        if password_validation_errors:
            print()
            pw_error_text = Text()
            pw_error_text.append("✗ ", style="bold red")
            pw_error_text.append("OpenSearch Password Validation Failed\n\n", style="bold red")
            pw_error_text.append("The DATABASE_USER_PASSWORD does not meet OpenSearch security requirements.\n\n",
                                 style="white")
            pw_error_text.append("Requirements:\n", style="bold white")
            pw_error_text.append("  • At least 8 characters\n", style="white")
            pw_error_text.append("  • At least one uppercase letter\n", style="white")
            pw_error_text.append("  • At least one lowercase letter\n", style="white")
            pw_error_text.append("  • At least one digit\n", style="white")
            pw_error_text.append("  • At least one special character (!@#$%^&*()_+-=.)\n", style="white")
            pw_error_text.append("  • Special characters limited to shell-safe and URL-safe characters\n\n",
                                 style="white")
            pw_error_text.append("Affected entries:\n", style="bold white")
            for db_id, error_msg in password_validation_errors.items():
                pw_error_text.append(f"  • {db_id}: ", style="yellow")
                pw_error_text.append(f"{error_msg}\n", style="red")
            pw_error_text.append("\nUpdate ", style="dim")
            pw_error_text.append("cas_vector_database.toml", style="bold cyan")
            pw_error_text.append(" to resolve.", style="dim")
            print(Panel(pw_error_text, title="[bold red]Password Validation Error[/bold red]",
                        border_style="red", padding=(1, 2)))
            print()

        layout = display_issues(generate_folder=generated_folder, required_fields=required_fields,
                                certs=missing_certs, incorrect_certs=incorrect_certs, mode="generate")
        print(layout)
        exit(1)
    else:
        # creating folder structure for generate folder
        if os.path.exists(generated_folder):
            if not os.path.exists(os.path.join(os.getcwd(), "backups")):
                os.mkdir(os.path.join(os.getcwd(), "backups"))
            now = datetime.now()
            dt_string = now.strftime("%Y-%m-%d_%H-%M")
            zip_folder(os.path.join(os.getcwd(), "backups", f"generatedFiles_{namespace}_{dt_string}"),
                       os.path.join(os.getcwd(), "generatedFiles", namespace))
            shutil.rmtree(generated_folder)
        create_generate_folder(trusted_certs_present, namespace=namespace)

        # steps to generate secrets
        generate_secrets = GenerateSecrets(namespace=namespace,
                                           content_assistant_properties=content_assistant_prop_dict,
                                           vector_database_properties=vector_database_prop_dict,
                                           logger=state["logger"])

        if content_assistant_prop:
            generate_secrets.create_content_assistant_secret()

            # Create AI provider SSL secrets for lightweight providers
            for ai_provider_id in content_assistant_prop_dict["_ai_providers_ids"]:
                provider_number = content_assistant_prop_dict["_ai_providers_ids"].index(ai_provider_id) + 1
                if content_assistant_prop_dict[ai_provider_id].get("SSL_ENABLED", False):
                    generate_secrets.create_ai_provider_ssl_secret(ai_provider_id=ai_provider_id,
                                                                   provider_number=provider_number)

            if content_assistant_prop_dict.get("MODELGATEWAY", {}).get("SSL_ENABLED", False):
                generate_secrets.create_modelgateway_ssl_secret()

            if "MODELGATEWAY" in content_assistant_prop_dict:
                # Use the TOML section key as the prefix so all configmap key names
                # and the secret name are derived from the actual property file header
                mg_prefix = "MODELGATEWAY"
                configmap_gen = GenerateConfigMaps(namespace=namespace, logger=state["logger"])
                configmap_gen.create_modelgateway_configmap(
                    prefix=mg_prefix,
                    use_ssl=content_assistant_prop_dict[mg_prefix].get("SSL_ENABLED", False),
                    ca_certs_secret_name=f"{mg_prefix.lower()}-certificate-secret",
                    gateway_url=content_assistant_prop_dict[mg_prefix].get("URL", "")
                )

            for vector_database_id in vector_database_prop_dict["_vector_database_ids"]:
                generate_secrets.create_vector_database_secret(
                    id=vector_database_id,
                    database_number=(vector_database_prop_dict["_vector_database_ids"].index(vector_database_id) + 1))
                if vector_database_prop_dict[vector_database_id]["DATABASE_SSL_ENABLED"]:
                    generate_secrets.create_vector_database_ssl_secret(id=vector_database_id)
                    if vector_database_prop_dict[vector_database_id]["DATABASE_AUTH_TYPE"].lower() == "oidc":
                        generate_secrets.create_vector_database_oidc_ssl_secret(id=vector_database_id)

            generate_secrets.create_content_admin_access_secret()
        if trusted_certs_present:
            generate_secrets.create_trusted_secrets()

        # steps to generate CR
        cr = GenerateCR(namespace=namespace,
                        content_assistant_properties=content_assistant_prop_dict,
                        vector_database_properties=vector_database_prop_dict,
                        deployment_properties=deployment_prop_dict,
                        ingress_properties=ingress_prop_dict,
                        logger=state["logger"])

        cr.generate_cr()

        # Generate metrics — always produce GENAI metrics regardless of deployment config
        metrics = GenerateMetrics(
            deployment_properties={"GENAI": True},
            namespace=namespace,
            logger=state["logger"]
        )
        metrics.generate_component_metrics("GENAI")

        # Generate OpenSearch YAMLs if CP4BA license and OpenSearch cluster hostname is present
        if (deployment_prop_dict.get("LICENSE", "").upper() == "CP4BA" and
                deployment_prop_dict.get("OPENSEARCH_CLUSTER_HOSTNAME")):
            # Read storage properties from deployment property file
            storage_props = {}
            with open(deployment_prop_file, 'r') as f:
                import toml
                full_deployment = toml.load(f)
                storage_props['SLOW_FILE_STORAGE_CLASSNAME'] = full_deployment.get('SLOW_FILE_STORAGE_CLASSNAME',
                                                                                   '<Required>')
                storage_props['BLOCK_STORAGE_CLASS'] = full_deployment.get('BLOCK_STORAGE_CLASS', '<Required>')

            generate_opensearch_yamls(namespace=namespace,
                                      deployment_properties=deployment_prop_dict,
                                      storage_properties=storage_props,
                                      vector_database_properties=vector_database_prop_dict,
                                      generated_folder=generated_folder,
                                      logger=state["logger"])

        # Generate README for the produced files
        try:
            state["logger"].info("Generating README for generated files")
            opensearch_generated = (
                deployment_prop_dict.get("LICENSE", "").upper() == "CP4BA"
                and bool(deployment_prop_dict.get("OPENSEARCH_CLUSTER_HOSTNAME"))
            )
            cas_readme = GenerateCASReadme(
                namespace=namespace,
                content_assistant_properties=content_assistant_prop_dict,
                vector_database_properties=vector_database_prop_dict,
                deployment_properties=deployment_prop_dict,
                ingress_properties=ingress_prop_dict,
                trusted_certs_present=trusted_certs_present,
                opensearch_generated=opensearch_generated,
                logger=state["logger"],
            )
            if cas_readme.generate_readme():
                state["logger"].info("✓ Generated files README created successfully")
                print(f"\n[green]✓ Generated files documentation created: generatedFiles/{namespace}/README.md[/green]")
            else:
                state["logger"].warning("⚠ Generated files README creation failed")
                print(f"\n[yellow]⚠ Generated files README creation failed[/yellow]")
        except Exception as e:
            state["logger"].error(f"Error generating README for generated files: {str(e)}")
            print(f"\n[yellow]⚠ Error generating README: {str(e)}[/yellow]")

    generate_generate_results(generated_folder)


def generate_opensearch_yamls(namespace, deployment_properties, storage_properties, vector_database_properties,
                              generated_folder, logger):
    """
    Generate OpenSearch cluster YAMLs from templates.
    Reads storage classes from storage_properties, cluster hostname from deployment_properties,
    and passwords from vector_database_properties.
    """
    import base64
    from helper_scripts.utilities.prerequisites_utilites import generate_secure_password

    try:
        logger.info("Generating OpenSearch cluster YAMLs")

        # Source and destination paths
        opensearch_descriptors_folder = os.path.join(os.getcwd(), "..", "descriptors", "opensearch")
        opensearch_generated_folder = os.path.join(generated_folder, "opensearch")

        # Create opensearch folder in generated files
        if not os.path.exists(opensearch_generated_folder):
            os.makedirs(opensearch_generated_folder)

        # Get values from storage properties
        slow_file_storage_class = storage_properties.get("SLOW_FILE_STORAGE_CLASSNAME", "<Required>")
        block_storage_class = storage_properties.get("BLOCK_STORAGE_CLASS", "<Required>")

        # Get cluster hostname from deployment properties
        cluster_hostname = deployment_properties.get("OPENSEARCH_CLUSTER_HOSTNAME", "<Required>")

        # Get password from vector database properties
        vectordb_props = vector_database_properties.get("VECTORDB", {})
        genai_password = vectordb_props.get("DATABASE_USER_PASSWORD", "<Required>")

        # Generate a random secure password for the admin user
        admin_password = generate_secure_password(length=24)
        logger.info("Generated secure admin password for OpenSearch cluster")

        # Base64 encode passwords
        admin_password_b64 = base64.b64encode(admin_password.encode()).decode()
        genai_password_b64 = base64.b64encode(genai_password.encode()).decode()

        yaml_files = [
            "opensearch_admin_secret.yaml",
            "opensearch_cluster.yaml",
            "opensearch_cluster_permission_job.yaml",
            "opensearch_genai_secret.yaml",
            "opensearch_route.yaml"
        ]

        for yaml_file in yaml_files:
            source_file = os.path.join(opensearch_descriptors_folder, yaml_file)
            dest_file = os.path.join(opensearch_generated_folder, yaml_file)

            if os.path.exists(source_file):
                with open(source_file, 'r') as f:
                    content = f.read()

                content = content.replace("REPLACE_NAMESPACE", namespace)

                if "cluster.yaml" in yaml_file:
                    content = content.replace("snapshotPVCStorageClass: REPLACE_STORAGECLASS",
                                              f"snapshotPVCStorageClass: {slow_file_storage_class}")
                    content = content.replace("REPLACE_BLOCK_STORAGECLASS", block_storage_class)
                else:
                    content = content.replace("REPLACE_STORAGECLASS", slow_file_storage_class)

                content = content.replace('"<base64-encoded-password>"', f'"{admin_password_b64}"')

                if "route" in yaml_file:
                    content = content.replace("apps.<cluster-name>.cp.fyre.ibm.com", cluster_hostname)

                if "genai_secret" in yaml_file:
                    content = content.replace(f'"{admin_password_b64}"', f'"{genai_password_b64}"')

                with open(dest_file, 'w') as f:
                    f.write(content)

                logger.info(f"Generated OpenSearch YAML: {yaml_file}")
            else:
                logger.warning(f"Source file not found: {source_file}")

        logger.info(f"OpenSearch YAMLs generated in: {opensearch_generated_folder}")

        # Create README with deployment instructions
        readme_content = f"""# OpenSearch Cluster Configuration

## Generated Files

The following OpenSearch cluster YAMLs have been generated:

1. **opensearch_admin_secret.yaml** - Admin user credentials
2. **opensearch_genai_secret.yaml** - GenAI service user credentials
3. **opensearch_route.yaml** - TLS certificate for OpenSearch routes
4. **opensearch_cluster.yaml** - OpenSearch cluster configuration
5. **opensearch_cluster_permission_job.yaml** - Job to configure permissions

## Deployment Instructions

1. Apply the secrets and certificate first:
   ```bash
   kubectl apply -f opensearch_admin_secret.yaml
   kubectl apply -f opensearch_genai_secret.yaml
   kubectl apply -f opensearch_route.yaml
   ```

2. Apply the OpenSearch cluster:
   ```bash
   kubectl apply -f opensearch_cluster.yaml
   ```

3. Wait for the cluster to be ready, then apply the permission job:
   ```bash
   kubectl apply -f opensearch_cluster_permission_job.yaml
   ```

## Vector Database Configuration

When using this OpenSearch cluster as your vector database, use the following values in your cas_vector_database.toml:

```toml
[VECTORDB]
DATABASE_TYPE = "Opensearch"
DATABASE_URL = "https://ica-opensearch.{namespace}.svc.cluster.local:9200"
DATABASE_USERNAME = "genai-service-user"
DATABASE_USER_PASSWORD = "{genai_password}"
DATABASE_SSL_ENABLED = true
DATABASE_AUTH_TYPE = "BASICAUTH"
```

**Important Notes:**
- The SSL certificate secret name will be automatically set to `ica-opensearch-tls-secret-route` in the CR when OpenSearch creation is enabled
- The certificate will be automatically created by cert-manager using the opensearch_route.yaml file
- Do NOT manually specify `DATABASE_SSL_CERTIFICATE_SECRET_NAME` in the property file - it will be handled automatically by the generate script
"""

        readme_file = os.path.join(opensearch_generated_folder, "README.md")
        with open(readme_file, 'w') as f:
            f.write(readme_content)

        logger.info("Generated README.md with deployment instructions")

    except Exception as e:
        logger.exception(f"Exception generating OpenSearch YAMLs: {str(e)}")


def _missing_prop_panel(namespace: str) -> Panel:
    """Return a red error Panel for a missing propertyFile/<namespace> folder."""
    tbl = Table.grid(padding=(0, 1))
    tbl.add_column(width=3)
    tbl.add_column(style="white")
    tbl.add_row(_STATUS_ICONS["error"],
                f"[red]Property files are missing for namespace:[/red] "
                f"[bold white]{namespace}[/bold white]")
    tbl.add_row("", "")
    tbl.add_row(_STATUS_ICONS["info"],
                "Run [bold cyan]python3 prerequisites.py gather[/bold cyan] first.")
    return Panel(
        tbl,
        title="[bold red]✗  Missing Property Files[/bold red]",
        border_style="red",
        padding=(1, 2),
    )


@app.command()
def validate(
        apply: bool = typer.Option(False, help="Apply all generated artifacts to the cluster"),
        skip_storage_class: bool = typer.Option(False, "--skip-storageclass", "-sc",
                                                help="Skip storage class validation"),
        skip_idp: bool = typer.Option(False, "--skip-idp", "-idp", help="Skip IDP validation", hidden=True),
        pvc_size: str = typer.Option('10Mi', "--pvc-size", "-pvc",
                                     help="Set size for sample persistent volume validation"),
        skip_vectordb: bool = typer.Option(False, "--skip-vectordb", "-vectordb",
                                           help="Skip Vector Database validation"),
        skip_api: bool = typer.Option(False, "--skip-api", "-api", help="Skip AI Provider API validation"),
):
    """
    Validate the prerequisites for IBM Content Assistant Deployment.
    """

    # By default, all validations are executed
    validate_storage_class = not skip_storage_class
    validate_idp = not skip_idp
    validate_vectordb = not skip_vectordb
    validate_api = not skip_api

    if not state["silent"]:
        scope_items = [
            ("Storage Classes", validate_storage_class),
            ("Vector Database Connectivity", validate_vectordb),
            ("AI Provider API Endpoints", validate_api),
        ]
        print()
        print(_mode_scope_panel(scope_items, title="✔  Validate — Prerequisite Checks"))
        print()

    # ── Operator-pod hint + copy command ─────────────────────────────────────
    hint_tbl = Table.grid(padding=(0, 1))
    hint_tbl.add_column(width=2, style="dim cyan")
    hint_tbl.add_column(style="white")
    hint_tbl.add_row("•", "Run validation from inside the IBM Content Assistant Operator pod")
    hint_tbl.add_row("•", "All required tools and libraries are pre-installed in the pod")
    hint_tbl.add_row("•", "In-cluster validation can reach private / internal endpoints")
    hint_tbl.add_row("•", "Use the command below to copy and run the script in the pod")

    hint_panel = Panel(
        hint_tbl,
        title="[bold cyan]💡 Hint[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )

    command_panel = Panel(
        Syntax(
            "cd ..\n"
            "export OPERATOR=$(kubectl get pods -l 'app.kubernetes.io/name=ibm-content-assistant-operator'"
            " | awk 'NR>1 {print $1}')\n"
            "kubectl cp scripts  $OPERATOR:/opt/ansible\n"
            "kubectl exec -it $OPERATOR -- bash\n"
            "cd /opt/ansible/scripts\n"
            "python3 prerequisites.py validate",
            "bash",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        ),
        title="[bold cyan]⌨  Copy & Run[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )

    print(Panel(
        Columns([hint_panel, command_panel], align="left", equal=True),
        title="[bold white]IBM Content Assistant Operator — In-Cluster Validation[/bold white]",
        border_style="bright_blue",
        padding=(0, 1),
    ))
    print()

    if not state["silent"]:
        # this is the user details object
        gather = g.GatherPrereqOptions(state["logger"], console)
        gather.collect_namespace()
    else:
        gather = sg.SilentGatherPrereqOptions(state["logger"],
                                              os.path.join("silent_config", "silent_install_prerequisites.toml"))
        # Individual components loaded:
        gather.silent_version(state["version_data"])
        gather.silent_namespace()

    namespace = gather.namespace
    state["logger"].info(f"Namespace: {namespace}")

    # Loading property folder locations
    prop_folder = os.path.join(os.getcwd(), "propertyFile", namespace)

    if not os.path.exists(prop_folder):
        state["logger"].info("Property files are missing. Please run the gather command first.")
        print()
        print(_missing_prop_panel(namespace))
        raise typer.Exit()

    # Validate passed pvc_size
    pvc_pattern = re.compile(r'^[0-9]+(mi|gi)$')
    if not re.match(pvc_pattern, pvc_size.lower()):
        pvc_tbl = Table.grid(padding=(0, 1))
        pvc_tbl.add_column(width=3)
        pvc_tbl.add_column(style="white")
        pvc_tbl.add_row(_STATUS_ICONS["error"],
                        "[red]Invalid[/red] [bold]--pvc-size[/bold] value "
                        f"[bold yellow]{pvc_size}[/bold yellow]")
        pvc_tbl.add_row("", "")
        pvc_tbl.add_row(_STATUS_ICONS["info"],
                        "Value must end in [bold cyan]Mi[/bold cyan] or [bold cyan]Gi[/bold cyan]"
                        "  [dim](e.g. 10Mi, 1Gi)[/dim]")
        print()
        print(Panel(pvc_tbl, title="[bold red]✗  Invalid Parameter[/bold red]",
                    border_style="red", padding=(1, 2)))
        state["logger"].info("The passed pvc_size is not valid. Size needs to be either ending in Mi or Gi")
        raise typer.Exit()

    ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
    trusted_certs_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs", "trusted-certs")

    # Loading generated folder location
    generated_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)

    # Loading property files locations
    content_assistant_prop_file = os.path.join(prop_folder, "cas_properties.toml")
    deployment_prop_file = os.path.join(prop_folder, "cas_deployment.toml")
    vector_database_prop_file = os.path.join(prop_folder, "cas_vector_database.toml")

    # Set defaults for property files
    idp_prop = None
    deployment_prop = None
    ingress_prop = None
    content_assistant_prop = None
    vector_database_prop = None

    # load the property files
    try:
        # Load property files if they exist
        if os.path.exists(content_assistant_prop_file):
            content_assistant_prop = ReadPropContentAssistant(content_assistant_prop_file, state["logger"])

        if os.path.exists(deployment_prop_file):
            deployment_prop = ReadPropDeployment(deployment_prop_file, state["logger"])

        if os.path.exists(vector_database_prop_file):
            vector_database_prop = ReadPropVectorDatabase(vector_database_prop_file, state["logger"])

        # Create dictionaries for property files if not None
        if vector_database_prop:
            vector_database_prop_dict = vector_database_prop.to_dict()
        else:
            vector_database_prop_dict = {}

        if content_assistant_prop:
            content_assistant_prop_dict = content_assistant_prop.to_dict()
        else:
            content_assistant_prop_dict = {}

        if deployment_prop:
            deployment_prop_dict = deployment_prop.to_dict()
        else:
            deployment_prop_dict = {}
    except TomlDecodeError:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)
    except Exception as e:
        state["logger"].exception(
            f"Exception when reading Property Files\n"
            f"Please Review your Property files for missing quotes and formatting.\n\n")
        exit(1)

    vobject = v.Validate(state["logger"],
                         content_assistant_prop=content_assistant_prop_dict,
                         vector_db_prop=vector_database_prop_dict,
                         deploy_prop=deployment_prop_dict,
                         pvc_size=pvc_size,
                         namespace=namespace)

    storageclass_number = len(vobject.get_unique_storageclass())

    # check for missing certificates
    missing_certs, incorrect_certs = check_ssl_folders_cas(content_assistant_prop=content_assistant_prop_dict,
                                                           vector_database_prop=vector_database_prop_dict,
                                                           ssl_cert_folder=ssl_cert_folder)
    # Collect missing fields from ALL property files
    required_fields = {}
    for prop_obj in (content_assistant_prop, deployment_prop, vector_database_prop, ingress_prop):
        if prop_obj is not None and prop_obj.missing_required_fields():
            required_fields.update(prop_obj.required_fields)

    any_missing = bool(required_fields)

    if any_missing or len(missing_certs) > 0 or len(incorrect_certs) > 0:
        layout = display_issues(required_fields=required_fields, certs=missing_certs,
                                incorrect_certs=incorrect_certs, mode="validate",
                                deployment_prop=deployment_prop_dict)
        print(layout)
        exit(1)
    else:
        # ── Running validation ────────────────────────────────────────────────
        print()
        print(Rule("[bold cyan]🔍  Running Validation Tests[/bold cyan]", style="bright_blue"))
        print()

        display = ValidationDisplay(console)

        # Register a test entry for each enabled validation category
        if validate_storage_class:
            display.add_test("storage", "Storage Class", "Infrastructure", total_items=storageclass_number)

        if validate_vectordb and vector_database_prop:
            vdb_count = vector_database_prop_dict.get("vector_database_number", 1)
            display.add_test("vectordb", "Vector Database", "Connectivity", total_items=vdb_count)

        if validate_api and content_assistant_prop:
            api_count = content_assistant_prop_dict.get("ai_providers_number", 1)
            display.add_test("ai_api", "AI Provider APIs", "Credentials", total_items=api_count)

        with display:
            # ── Storage Class ─────────────────────────────────────────────────
            if validate_storage_class:
                display.start_test("storage")
                sc_progress = DisplayProgressAdapter(display, "storage")
                sc_task = sc_progress.add_task("Validate Storage Class", total=storageclass_number)
                try:
                    vobject.validate_all_storage_classes(sc_task, sc_progress)
                    sc_ok = all(
                        result for key, result in vobject.is_validated.items()
                        if key in vobject.get_unique_storageclass()
                    )
                    display.complete_test("storage", success=sc_ok,
                                         message="All storage classes validated" if sc_ok else "Storage class validation failed",
                                         failure_reason="" if sc_ok else "One or more storage classes could not be validated.",
                                         remediation="Ensure the storage class exists in the cluster and supports ReadWriteMany access mode.")
                except Exception as _e:
                    display.complete_test("storage", success=False,
                                         failure_reason=str(_e),
                                         remediation="Check cluster connectivity and storage class configuration.")

            # ── Vector Database ───────────────────────────────────────────────
            if validate_vectordb:
                if vector_database_prop:
                    display.start_test("vectordb")
                    vdb_progress = DisplayProgressAdapter(display, "vectordb")
                    vdb_task = vdb_progress.add_task("Validate Database", total=vdb_count)
                    try:
                        vobject.validate_vector_databases(vdb_task, vdb_progress)
                        vdb_ids = vector_database_prop_dict.get("_vector_database_ids", [])
                        vdb_ok = all(vobject.is_validated.get(i, False) for i in vdb_ids) if vdb_ids else True
                        display.complete_test("vectordb", success=vdb_ok,
                                             message="All vector databases reachable" if vdb_ok else "Vector database validation failed",
                                             failure_reason="" if vdb_ok else "One or more vector databases could not be reached or authenticated.",
                                             remediation="Check DATABASE_URL, authentication credentials, and SSL certificates in cas_vector_database.toml.")
                    except Exception as _e:
                        display.complete_test("vectordb", success=False,
                                             failure_reason=str(_e),
                                             remediation="Review cas_vector_database.toml and network connectivity.")
                else:
                    display.skip_test("vectordb", reason="No vector database property file found")

            # ── AI Provider APIs ──────────────────────────────────────────────
            if validate_api:
                if content_assistant_prop:
                    display.start_test("ai_api")
                    api_progress = DisplayProgressAdapter(display, "ai_api")
                    api_task = api_progress.add_task("Validate AI Provider APIs", total=api_count)
                    try:
                        vobject.validate_ai_provider_apis(api_task, api_progress)
                        api_ids = content_assistant_prop_dict.get("_ai_providers_ids", [])
                        api_ok = all(vobject.is_validated.get(i, False) for i in api_ids) if api_ids else True
                        display.complete_test("ai_api", success=api_ok,
                                             message="All AI provider credentials validated" if api_ok else "AI provider validation failed",
                                             failure_reason="" if api_ok else "One or more AI provider credentials are invalid or unreachable.",
                                             remediation="Check API_KEY, SPACE_ID/USERNAME, and URL in cas_properties.toml for each AI provider.")
                    except Exception as _e:
                        display.complete_test("ai_api", success=False,
                                             failure_reason=str(_e),
                                             remediation="Review cas_properties.toml AI provider configuration.")
                else:
                    display.skip_test("ai_api", reason="No content assistant property file found")

        # Display detailed failure information after the live display closes
        display.display_failures()

        # ── Post-validation summary & apply prompts ───────────────────────────
        _qs_style_ok = Style([
            ("qmark",    "fg:ansicyan bold"),
            ("question", "bold"),
            ("answer",   "fg:ansicyan bold"),
        ])
        _qs_style_warn = Style([
            ("qmark",    "fg:ansiyellow bold"),
            ("question", "bold"),
            ("answer",   "fg:ansiyellow bold"),
        ])

        if all(vobject.is_validated.values()):
            print()
            print(Rule("[bold green]✓  All Prerequisites Validated Successfully[/bold green]",
                       style="green"))
            print()

            if apply:
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_configmaps()
                vobject.auto_apply_metrics()
                vobject.auto_apply_cr()
            else:
                # Context before prompts
                apply_tbl = Table.grid(padding=(0, 1))
                apply_tbl.add_column(width=3)
                apply_tbl.add_column(style="white")
                apply_tbl.add_row(_STATUS_ICONS["success"],
                                  "SSL certificates and Kubernetes Secrets")
                apply_tbl.add_row(_STATUS_ICONS["success"],
                                  "ConfigMaps")
                apply_tbl.add_row(_STATUS_ICONS["success"],
                                  "Metrics")
                apply_tbl.add_row(_STATUS_ICONS["success"],
                                  "Custom Resource (CR) YAML")
                print(Panel(
                    apply_tbl,
                    title="[bold cyan]📦  Ready to Apply — Artifacts[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                ))
                print()

                apply_ssls_secrets = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply SSL certificates and Secrets to the cluster?",
                    default=True,
                    style=_qs_style_ok,
                )
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()

                print()
                apply_configmaps = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply ConfigMaps to the cluster?",
                    default=True,
                    style=_qs_style_ok,
                )
                if apply_configmaps:
                    vobject.auto_apply_configmaps()

                print()
                apply_metrics = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply Metrics to the cluster?",
                    default=True,
                    style=_qs_style_ok,
                )
                if apply_metrics:
                    vobject.auto_apply_metrics()

                print()
                apply_cr = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply Custom Resources (CRs) to the cluster?",
                    default=True,
                    style=_qs_style_ok,
                )
                if apply_cr:
                    vobject.auto_apply_cr()
        else:
            print()
            print(Rule("[bold yellow]⚠  Some Validation Checks Failed[/bold yellow]",
                       style="yellow"))
            print()

            warn_tbl = Table.grid(padding=(0, 1))
            warn_tbl.add_column(width=3)
            warn_tbl.add_column(style="white")
            warn_tbl.add_row(_STATUS_ICONS["warn"],
                             "Review the validation results above and fix any issues.")
            warn_tbl.add_row(_STATUS_ICONS["warn"],
                             "Applying artifacts now may cause deployment problems.")
            print(Panel(
                warn_tbl,
                title="[bold yellow]⚠  Proceed with Caution[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            ))
            print()

            if apply:
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_configmaps()
                vobject.auto_apply_metrics()
                vobject.auto_apply_cr()
            else:
                apply_ssls_secrets = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply SSL certificates and Secrets despite validation failures?",
                    default=False,
                    style=_qs_style_warn,
                )
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()

                print()
                apply_configmaps = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply ConfigMaps despite validation failures?",
                    default=False,
                    style=_qs_style_warn,
                )
                if apply_configmaps:
                    vobject.auto_apply_configmaps()

                print()
                apply_metrics = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply Metrics despite validation failures?",
                    default=False,
                    style=_qs_style_warn,
                )
                if apply_metrics:
                    vobject.auto_apply_metrics()

                print()
                apply_cr = safe_questionary_prompt(
                    questionary.confirm,
                    message="Apply Custom Resources (CRs) despite validation failures?",
                    default=False,
                    style=_qs_style_warn,
                )
                if apply_cr:
                    vobject.auto_apply_cr()


if __name__ == "__main__":
    app()
