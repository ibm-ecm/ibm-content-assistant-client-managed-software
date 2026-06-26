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
from datetime import datetime
from typing_extensions import Annotated
from typing import Optional

import typer
from rich import print
from rich.columns import Columns
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TimeElapsedColumn,
    MofNCompleteColumn, BarColumn, TaskProgressColumn, TextColumn,
)
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.text import Text
from toml.decoder import TomlDecodeError

from helper_scripts.gather import gather_prerequisites as g
from helper_scripts.gather import silent_gather_prerequisites as sg
from helper_scripts.generate.generate_cr import GenerateCR
from helper_scripts.generate.generate_secrets import GenerateSecrets
from helper_scripts.property import property as p
from helper_scripts.property.read_prop import *
from helper_scripts.property.read_prop import ReadPropOpenSearch
from helper_scripts.utilities.interface import clear, generate_gather_results, generate_generate_results, \
    display_issues, display_prereq_passed
from helper_scripts.utilities.prerequisites_utilites import zip_folder, \
    create_generate_folder, check_ssl_folders, check_trusted_certs
from helper_scripts.utilities.utilities import read_version_toml, prereq_checks
from helper_scripts.validate import validate as v

__version__ = "3.0.0"

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

    if ctx.invoked_subcommand == "gather":
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
        prereq_summary = display_prereq_passed(results)
        print(prereq_summary)
        print()


def setup_logger(file_log_level):
    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Setup console logger
    shell_handler = RichHandler()
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


def display_mode_version(mode: str, description: str):
    """
        Display the mode and version of the script.
    """
    clear(console)
    print()
    msg = f"Version: {__version__}\n" \
          f"Mode: {mode}\n" \
          f"{description}"

    if state["silent"]:
        msg += "\nSilent Mode Enabled"

    print(Panel.fit(msg, title="IBM Content Assistant Deployment Prerequisites -- CLI", border_style="green"))
    print()


@app.command()
def gather():
    """
    Gather the prerequisites for IBM Content Assistant Deployment.
    """

    if not state["silent"]:
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

        # Only collect vector database details if not using OpenSearch
        if not gather.create_opensearch_cluster:
            clear(console)
            gather.collect_vector_db_details()

        # clear(console)
        # gather.collect_content_assistant_admin_access()

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
        gather.silent_network_policies_support()
        gather.silent_license_model()
        gather.silent_ai_provider_type()
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

    layout = generate_gather_results(property_obj.property_folder,
                                     gather.to_dict())

    print(layout)


@app.command()
def generate():
    """
    Generate the prerequisites for IBM Content Assistant Deployment.
    """

    if not state["silent"]:
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
        print(Panel.fit(Text(f"Property files are missing for namespace: {namespace}.\n\n"
                             "Please run the python3 prerequisites.py gather command first."), style="bold red"))
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
    content_assistant_prop=None
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

    missing_certs, incorrect_certs = check_ssl_folders(content_assistant_prop=content_assistant_prop_dict,
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
                        state["logger"].error(f"OpenSearch password validation failed for {vector_database_id}: {error_msg}")

    # Collect missing fields
    # All missing required fields are collected in each instance
    required_fields = {}
    # clear(console)
    if content_assistant_prop.missing_required_fields():
        required_fields = content_assistant_prop.required_fields

    if content_assistant_prop.missing_required_fields() or cert_failed or password_validation_errors:
        # Add password validation errors to the display
        if password_validation_errors:
            print()
            print(Panel.fit(Text("OpenSearch Password Validation Failed", style="bold red")))
            for db_id, error_msg in password_validation_errors.items():
                print(Panel.fit(Text(f"{db_id}: {error_msg}", style="red")))
            print()
            print(Panel.fit(Text("Please update the DATABASE_USER_PASSWORD in cas_vector_database.toml to meet OpenSearch security requirements:\n"
                                "- At least 8 characters\n"
                                "- At least one uppercase letter\n"
                                "- At least one lowercase letter\n"
                                "- At least one digit\n"
                                "- At least one special character (!@#$%^&*()_+-=.)\n"
                                "- Special characters are limited to shell-safe and URL-safe characters", style="yellow")))
        
        layout = display_issues(generate_folder=generated_folder, required_fields=required_fields,
                                certs=missing_certs, incorrect_certs=incorrect_certs,mode="generate")
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
                    generate_secrets.create_ai_provider_ssl_secret(ai_provider_id=ai_provider_id, provider_number=provider_number)
            
            for vector_database_id in vector_database_prop_dict["_vector_database_ids"]:
                generate_secrets.create_vector_database_secret(id=vector_database_id,database_number=(vector_database_prop_dict["_vector_database_ids"].index(vector_database_id)+1))
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
        
        # Generate OpenSearch YAMLs if CP4BA license and OpenSearch cluster hostname is present
        if (deployment_prop_dict.get("LICENSE", "").upper() == "CP4BA" and
            deployment_prop_dict.get("OPENSEARCH_CLUSTER_HOSTNAME")):
            # Read storage properties from deployment property file
            storage_props = {}
            with open(deployment_prop_file, 'r') as f:
                import toml
                full_deployment = toml.load(f)
                storage_props['SLOW_FILE_STORAGE_CLASSNAME'] = full_deployment.get('SLOW_FILE_STORAGE_CLASSNAME', '<Required>')
                storage_props['BLOCK_STORAGE_CLASS'] = full_deployment.get('BLOCK_STORAGE_CLASS', '<Required>')
            
            generate_opensearch_yamls(namespace=namespace,
                                     deployment_properties=deployment_prop_dict,
                                     storage_properties=storage_props,
                                     vector_database_properties=vector_database_prop_dict,
                                     generated_folder=generated_folder,
                                     logger=state["logger"])

    layout = generate_generate_results(generated_folder)

    print(layout)


def generate_opensearch_yamls(namespace, deployment_properties, storage_properties, vector_database_properties, generated_folder, logger):
    """
    Generate OpenSearch cluster YAMLs from templates
    Reads storage classes from storage_properties, cluster hostname from deployment_properties,
    and passwords from vector_database_properties
    """
    import base64
    import shutil
    from helper_scripts.utilities.prerequisites_utilites import generate_secure_password
    
    try:
        logger.info("Generating OpenSearch cluster YAMLs")
        
        # Source and destination paths
        opensearch_descriptors_folder = os.path.join(os.getcwd(), "..", "descriptors", "opensearch")
        opensearch_generated_folder = os.path.join(generated_folder, "opensearch")
        
        # Create opensearch folder in generated files
        if not os.path.exists(opensearch_generated_folder):
            os.makedirs(opensearch_generated_folder)
        
        # Get values from storage properties (storage configuration)
        slow_file_storage_class = storage_properties.get("SLOW_FILE_STORAGE_CLASSNAME", "<Required>")
        block_storage_class = storage_properties.get("BLOCK_STORAGE_CLASS", "<Required>")
        
        # Get cluster hostname from deployment properties
        cluster_hostname = deployment_properties.get("OPENSEARCH_CLUSTER_HOSTNAME", "<Required>")
        
        # Get password from vector database properties (VECTORDB section)
        vectordb_props = vector_database_properties.get("VECTORDB", {})
        genai_password = vectordb_props.get("DATABASE_USER_PASSWORD", "<Required>")
        
        # Generate a random secure password for the admin user
        admin_password = generate_secure_password(length=24)
        logger.info(f"Generated secure admin password for OpenSearch cluster")
        
        # Base64 encode passwords
        admin_password_b64 = base64.b64encode(admin_password.encode()).decode()
        genai_password_b64 = base64.b64encode(genai_password.encode()).decode()
        
        # List of YAML files to process
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
                # Read the file
                with open(source_file, 'r') as f:
                    content = f.read()
                
                # Replace placeholders
                content = content.replace("REPLACE_NAMESPACE", namespace)
                
                # For opensearch_cluster.yaml, use different storage classes for different purposes
                if "cluster.yaml" in yaml_file:
                    # Replace snapshotPVCStorageClass with SLOW_FILE_STORAGE_CLASSNAME
                    content = content.replace("snapshotPVCStorageClass: REPLACE_STORAGECLASS",
                                            f"snapshotPVCStorageClass: {slow_file_storage_class}")
                    # Replace data and deployment storageClass with BLOCK_STORAGE_CLASS
                    content = content.replace("storageClass: REPLACE_STORAGECLASS",
                                            f"storageClass: {block_storage_class}")
                else:
                    # For other files, use the default replacement
                    content = content.replace("REPLACE_STORAGECLASS", slow_file_storage_class)
                
                content = content.replace('"<base64-encoded-password>"', f'"{admin_password_b64}"')
                
                # For opensearch_route.yaml, replace cluster hostname placeholder
                if "route" in yaml_file:
                    content = content.replace("apps.<cluster-name>.cp.fyre.ibm.com", cluster_hostname)
                
                # For genai secret, replace the genai password
                if "genai_secret" in yaml_file:
                    content = content.replace(f'"{admin_password_b64}"', f'"{genai_password_b64}"')
                
                # Write the modified content
                with open(dest_file, 'w') as f:
                    f.write(content)
                
                logger.info(f"Generated OpenSearch YAML: {yaml_file}")
            else:
                logger.warning(f"Source file not found: {source_file}")
        
        logger.info(f"OpenSearch YAMLs generated in: {opensearch_generated_folder}")
        
        # Create a README file with vector database configuration instructions
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



@app.command()
def validate(
        apply: bool = typer.Option(False, help="Apply all generated artifacts to the cluster"),
        skip_storage_class: bool = typer.Option(False, "--skip-storageclass", "-sc", help="Skip storage class validation"),
        skip_idp: bool = typer.Option(False, "--skip-idp", "-idp", help="Skip IDP validation", hidden=True),
        pvc_size: str = typer.Option('10Mi', "--pvc-size", "-pvc", help="Set size for sample persistent volume validation"),
        skip_vectordb: bool = typer.Option(False, "--skip-vectordb", "-vectordb", help="Skip Vector Database validation"),
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

    hint_panel = Panel.fit(
        "- Run the validation from the IBM Content Assistant Operator \n"
        "- All tools and libraries are installed \n"
        "- Validation from within the your cluster can test private connections \n"
        "- See the below command to copy the folder and run the validation.",
        title="Hint"
    )

    command_panel = (Panel.fit(
        Syntax("cd ..\n"
               "export OPERATOR=$(kubectl get pods -l 'name=ibm-content-assistant-operator' | awk 'NR>1 {print $1}')\n"
               "kubectl cp scripts  $OPERATOR:/opt/ansible\n"
               "kubectl exec -it $OPERATOR -- bash\n"
               "cd /opt/ansible/scripts\n"
               "python3 prerequisites.py validate",
               "bash", theme="ansi_dark"
               ),
        title="Command"
    ))

    operator_panel = Panel(Columns([hint_panel, command_panel], align="center", equal=True),
                           title="IBM Content Assistant Operator", border_style="cyan")
    # for now we are not sure if validate mode can be run from the operator
    #print(operator_panel)
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
        print(Panel.fit(Text(f"Property files are missing for namespace: {namespace}.\n\n"
                             "Please run the python3 prerequisites.py gather command first."), style="bold red"))
        raise typer.Exit()
    
    # Validate passed pvc_size 
    # Write a regex match for pvc_size 
    pvc_pattern = re.compile(r'^[0-9]+(mi|gi)$')
    if not re.match(pvc_pattern, pvc_size.lower()):
        print(Panel.fit(Text("Invalid pvc_size.\n"
                             "Size needs to be either ending in Mi or Gi"), style="bold red"))
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

    # clear(console)
    vobject = v.Validate(state["logger"],
                         content_assistant_prop=content_assistant_prop_dict,
                         vector_db_prop=vector_database_prop_dict,
                         deploy_prop=deployment_prop_dict,
                         pvc_size=pvc_size,
                         namespace=namespace)

    storageclass_number = len(vobject.get_unique_storageclass())

    # check for missing certificates
    missing_certs, incorrect_certs = check_ssl_folders(content_assistant_prop=content_assistant_prop_dict,
                                                       vector_database_prop=vector_database_prop_dict,
                                                       ssl_cert_folder=ssl_cert_folder)
    # Collect missing fields
    # All missing required fields are collected in each instance
    required_fields = {}
    if vector_database_prop.missing_required_fields():
        required_fields = vector_database_prop.required_fields

    if vector_database_prop.missing_required_fields()  or len(missing_certs) > 0 or len(
            incorrect_certs) > 0:
        layout = display_issues(required_fields=required_fields, certs=missing_certs,
                                incorrect_certs=incorrect_certs, mode="validate",deployment_prop=deployment_prop_dict)
        print(layout)
        exit(1)
    else:

        # starting validation
        print(Panel.fit(Text("IBM Content Assistant Validation"), style="bold cyan"))
        print()

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=False,
        ) as progress:

            # So far for validation, the storage class and vector database URL will be validated
            # Adding storage classes validation task only if storageclass flag is True
            if validate_storage_class:
                task1 = progress.add_task("[green]Validate Storage Class", total=storageclass_number)
            # Adding databases validation task only if database flag is True
            if validate_vectordb:
                if vector_database_prop:
                    task2 = progress.add_task("[yellow]Validate Database", total=vector_database_prop_dict["vector_database_number"])
            # Adding provider API validation task only if api flag is True
            if validate_api:
                if content_assistant_prop:
                    task3 = progress.add_task("[cyan]Validate AI Provider APIs", total=content_assistant_prop_dict["ai_providers_number"])


            while not progress.finished:

                # Validating storage classes only if storageclass flag is True
                if validate_storage_class:
                    vobject.validate_all_storage_classes(task1, progress)

                # Validating storage classes only if storageclass flag is True
                if validate_vectordb:
                    vobject.validate_vector_databases(task2, progress)

                # Validating AI Provider APIs only if api flag is True
                if validate_api:
                    vobject.validate_ai_provider_apis(task3, progress)

        # Apply secrets and CR if requested
        if all(vobject.is_validated.values()):
            print()
            print(Panel.fit(Text("All prerequisites are validated"), style="bold green"))
            print()
            if apply:
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_cr()
            else:
                apply_ssls_secrets = Confirm.ask("Do you want to apply the SSL & Secrets?")
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                apply_cr = Confirm.ask("Do you want to apply the CR?")
                if apply_cr:
                    vobject.auto_apply_cr()
        else:
            print()
            print(Panel.fit(Text("All prerequisites checks have not passed!"), style="bold red"))
            print()
            if apply:
                vobject.auto_apply_secrets_ssl()
                vobject.auto_apply_cr()
            else:
                apply_ssls_secrets = Confirm.ask("Do you want to apply the SSL & Secrets?")
                if apply_ssls_secrets:
                    vobject.auto_apply_secrets_ssl()
                apply_cr = Confirm.ask("Do you want to apply the CR?")
                if apply_cr:
                    vobject.auto_apply_cr()


if __name__ == "__main__":
    app()
