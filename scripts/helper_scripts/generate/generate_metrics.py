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
Module for generating IBM Service Meter Definition YAML files for Content Assistant components.
Handles ICA GenAI metrics definitions.
"""

import os
from logging import Logger
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader


class GenerateMetrics:
    """
    Generate usage metering metrics YAML files for deployed Content Assistant components.

    This class handles the generation of IBMServiceMeterDefinition resources for:
    - ICA GenAI (IBM Content Assistant GenAI deployment)

    The metrics are generated from Jinja templates stored in the metrics_templates directory.
    """

    def __init__(
        self,
        deployment_properties: dict,
        namespace: str,
        logger: Optional[Logger] = None
    ):
        """
        Initialize the metrics generator.

        Args:
            deployment_properties: Dictionary containing deployment configuration.
                                   Set {'GENAI': True} to enable GenAI metrics generation.
            namespace: Kubernetes namespace for the deployment
            logger: Optional logger instance for logging operations
        """
        self._logger = logger
        self._deployment_properties = deployment_properties
        self._namespace = namespace

        # Set up paths - always use absolute paths relative to this file's location
        # This ensures consistency whether running from project root or scripts directory
        script_dir = Path(__file__).parent  # .../scripts/helper_scripts/generate/
        self._templates_dir = script_dir / "metrics_templates"

        # Generated files go in scripts/generatedFiles/<namespace>/metrics
        # Navigate up from generate/ to scripts/ directory
        scripts_dir = script_dir.parent.parent  # Up 2 levels from generate/ to scripts/
        self._generated_folder = scripts_dir / "generatedFiles" / self._namespace / "metrics"

        # Ensure generated folder exists
        self._generated_folder.mkdir(parents=True, exist_ok=True)

        # Set up Jinja2 environment
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self._templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def _log_info(self, message: str) -> None:
        if self._logger:
            self._logger.info(message)

    def _log_error(self, message: str) -> None:
        if self._logger:
            self._logger.error(message)

    def generate_component_metrics(self, component: str) -> bool:
        """
        Generate the metrics YAML for the given component.

        Currently only 'GENAI' is supported. The output file is always
        ``ica-genai-metrics.yaml`` and the only template variable is
        ``namespace``.

        Args:
            component: Component name — must be 'GENAI'

        Returns:
            bool: True if generation was successful
        """
        if not self._deployment_properties.get(component, False):
            self._log_info(f"{component} is not enabled, skipping metrics generation")
            return True

        if component != "GENAI":
            self._log_error(f"Unsupported metrics component: {component}")
            return False

        template_name = "ica-genai-metrics.yaml"
        output_filename = "ica-genai-metrics.yaml"

        template_path = self._templates_dir / template_name
        if not template_path.exists():
            self._log_error(f"Template not found: {template_path}")
            return False

        self._log_info(f"Generating GENAI metrics from template {template_name}")

        try:
            template = self._jinja_env.get_template(template_name)
            rendered_content = template.render(namespace=self._namespace)
            output_path = self._generated_folder / output_filename
            with open(output_path, 'w') as f:
                f.write(rendered_content)
            self._log_info(f"✓ Generated GENAI metrics: {output_filename}")
            return True
        except Exception as e:
            self._log_error(f"Error generating metrics from template {template_name}: {str(e)}")
            return False

# Made with Bob
