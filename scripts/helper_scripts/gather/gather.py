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
import sys
from enum import Enum
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from rich import print
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.text import Text
import questionary
from questionary import Style
from prompt_toolkit.formatted_text import FormattedText
import typer

from ..utilities.interface import clear
from ..utilities.kubernetes_utilites import KubernetesUtilities
from ..utilities.operator_config import (
    get_operator_metadata,
    OperatorType
)
from ..utilities.prerequisites_utilites import check_pem_cert_format, \
    connect_to_server
from ..utilities.registry_auth import RegistryAuthenticator, RegistryConfig, RegistryCredentials
from ..utilities.questionary_utils import handle_cancelled_prompt


# create a class to gather all deployment options from the user for the cleanup deployment script
class GatherOptions:
    class OptionalComponents(Enum):
        genai_connector = 1
        # genai_connector is the IBM Content Assistant (CASCluster) component

    # Create an enum for all platform types
    class Platform(Enum):
        OCP = 1
        other = 2

    class LicenseModel(Enum):
        Content_Cortex_Essentials = 1
        CP4BA = 2

    class Version:
        CASVersion = Enum(
            value='CASVersion',
            names=[("1.0.0", 1)]
        )

        def __init__(self, cas_version: CASVersion):
            self._cas_version = cas_version

    # Script type options are cleanup,deploy,load_extract and upgrade
    def __init__(self, logger, console, script_type="cleanup", dev=False, tls_verify=True):
        self._script_type = script_type
        self._ocp_logged_in = False
        self._namespace = None
        self._podman_available = False
        self._skopeo_available = False
        self._sensitive_collect = False
        self._logger = logger
        self._console = console
        self._platform = self.Platform(1).name
        self._missing_tools = []
        self._cas_version = "1.0.0"
        self._accept_license = False
        self._license_model = None  # Set by collect_license_model; "fncm" or "cp4ba"
        self._selected_operators: List[OperatorType] = []
        self._entitlement_key_valid = False
        self._entitlement_key = ''
        self._private_registry = False
        self._private_registry_valid = False
        self._private_registry_host = ''
        self._private_registry_port = 5000
        self._private_registry_username = ''
        self._private_registry_password = ''
        self._private_registry_ssl_enabled = False
        self._private_registry_ssl_cert = ''
        self._private_registry_full_server = ''
        self._private_registry_path = ''
        self._private_catalog = True
        self._all_channels = False
        self._components = set()
        self._current_namespace = None
        if dev:
            self._runtime_mode = "dev"
            self._registry = "preprod.icr.io"
        else:
            self._runtime_mode = "prod"
            self._registry = "cp.icr.io"
        self._silent_mode = False
        # Initialize Kubernetes client
        self._k = KubernetesUtilities(self._logger)
        self._tls_verify = tls_verify

    @property
    def cas_version(self):
        return self._cas_version

    @property
    def all_channels(self):
        return self._all_channels

    @property
    def accept_license(self):
        return self._accept_license

    @property
    def sensitive_collect(self):
        return self._sensitive_collect

    @property
    def components(self):
        return self._components

    @components.setter
    def components(self, value):
        self._components = set(value)

    @property
    def namespace(self):
        return self._namespace

    @property
    def podman_available(self):
        return self._podman_available

    @podman_available.setter
    def podman_available(self, value):
        self._podman_available = value

    @property
    def private_registry(self):
        return self._private_registry

    @private_registry.setter
    def private_registry(self, value):
        self._private_registry = value

    @property
    def private_registry_full_server(self):
        return self._private_registry_full_server

    @private_registry_full_server.setter
    def private_registry_full_server(self, value):
        self._private_registry_full_server = value

    @property
    def private_registry_server(self):
        return self._private_registry_full_server

    @property
    def platform(self):
        return self._platform

    @platform.setter
    def platform(self, value):
        self._platform = value

    @property
    def private_catalog(self):
        return self._private_catalog

    @property
    def private_registry_valid(self):
        return self._private_registry_valid

    @property
    def runtime_mode(self):
        return self._runtime_mode.lower()

    @property
    def silent_mode(self):
        return self._silent_mode

    @property
    def registry(self):
        return self._registry.lower()

    @property
    def entitlement_key_valid(self):
        return self._entitlement_key_valid

    @property
    def entitlement_key(self):
        return self._entitlement_key


    @property
    def license_model(self):
        """Return the selected license model: 'fncm' or 'cp4ba'."""
        return self._license_model

    @property
    def selected_operators(self) -> List[OperatorType]:
        """Return the list of OperatorType enums selected for deployment."""
        return self._selected_operators

    @selected_operators.setter
    def selected_operators(self, value: List[OperatorType]):
        self._selected_operators = value

    @property
    def private_registry_port(self):
        return self._private_registry_port

    @property
    def private_registry_username(self):
        return self._private_registry_username

    @property
    def private_registry_password(self):
        return self._private_registry_password

    def collect_operator_type(self, operator_status: dict = None,
                              op_classifications: dict = None,
                              op_key_to_type: dict = None,
                              version_data: dict = None,
                              migration_warning: str = None,
                              migration_warning_title: str = None,
                              force_mode: bool = False):
        """
        Configure IBM Content Assistant operators for deployment.

        Displays a Rich panel summarising what will happen (install / upgrade /
        force-redeploy) and then presents a questionary checkbox so the user can
        opt operators in or out.  Mandatory operators (usage-metering, and
        license-service for CP4BA licenses) are auto-added outside the checkbox
        in normal mode and appear as pre-checked entries in force mode.

        After this method returns, ``self.selected_operators`` contains the final
        ``List[OperatorType]`` that the deploy flow will act on.

        Args:
            operator_status:       Dict of {op_key: {installed, current_version,
                                   is_current, needs_action, action, target_version}}.
            op_classifications:    Dict of {op_key: class} where class is one of:
                                     'mandatory'  – auto-deployed, hidden from checkbox
                                     'upgrade'    – installed, needs version bump → pre-checked
                                     'install'    – not installed, required → pre-checked
                                     'current'    – installed at target → panel only
                                     'available'  – not installed, optional → unchecked
            op_key_to_type:        Mapping of op_key → OperatorType enum.
            version_data:          Parsed version.toml; restricts the UI to operators
                                   that are available in this release.
            migration_warning:     Optional Rich-markup string rendered side-by-side
                                   with the operator panel when set.
            migration_warning_title: Optional title for the migration warning panel.
            force_mode:            When True, mandatory operators appear in the
                                   checkbox so the user can opt them out.
        """
        try:
            self._logger.info("Configuring operators for deployment")

            print()

            _cls         = op_classifications or {}
            _key_to_type = op_key_to_type or {}

            # ── Checkbox style ────────────────────────────────────────────────
            _checkbox_style = questionary.Style([
                ('selected',          'fg:#98c379 bold'),
                ('pointer',           'fg:#61afef bold'),
                ('highlighted',       'fg:#ffffff'),
                ('answer',            'fg:#98c379 bold'),
                ('checkbox',          'fg:#e5c07b'),
                ('checkbox-selected', 'fg:#98c379'),
            ])

            # ── Display names ─────────────────────────────────────────────────
            _display = {
                'content-assistant': 'Content Assistant Operator',
                'usage-metering':    'Usage Metering Operator',
                'licensing':         'License Service Operator',
            }

            # ── Derive the set of op keys present in version.toml ─────────────
            _toml_key_to_op = {'license-service': 'licensing'}
            _available_in_release: set = set()
            for _tk, _sec in (version_data or {}).items():
                if isinstance(_sec, dict) and 'HELM_CHART_NAME' in _sec:
                    _available_in_release.add(_toml_key_to_op.get(_tk, _tk))

            def _in_release(key: str) -> bool:
                return not _available_in_release or key in _available_in_release

            def _cls_is(key: str, *classes) -> bool:
                return _cls.get(key) in classes

            # ── Panel helpers ─────────────────────────────────────────────────
            def _version_line(op_key: str, label: str) -> str:
                info         = (operator_status or {}).get(op_key, {})
                target_v     = info.get('target_version', '')
                current_v    = info.get('current_version', '')
                installed    = info.get('installed', False)
                action       = info.get('action', 'install')
                is_cur       = info.get('is_current', False)
                install_type = info.get('installation_type', '')

                _force_redeploy = force_mode and is_cur and _cls.get(op_key) == 'upgrade'

                if _force_redeploy:
                    return (
                        f"  [yellow]↑[/yellow]  [bold]{label}[/bold]  "
                        f"[yellow]{current_v}[/yellow] [dim]→[/dim] [green]{target_v}[/green] "
                        f"[dim](force)[/dim]\n"
                    )
                elif is_cur:
                    return f"  [green]✓[/green]  [bold]{label}[/bold]  [dim]{current_v}[/dim]\n"
                elif installed and action in ('upgrade', 'downgrade'):
                    if current_v in ('unknown', '', None) and install_type in ('YAML', 'OLM'):
                        _from = f"[dim]({install_type})[/dim]"
                    else:
                        _from = f"[yellow]{current_v}[/yellow]"
                    return f"  [yellow]↑[/yellow]  [bold]{label}[/bold]  {_from} [dim]→[/dim] [green]{target_v}[/green]\n"
                else:
                    return f"  [cyan]＋[/cyan]  [bold]{label}[/bold]  [green]{target_v}[/green]\n"

            def _render_operator_panel(body: str, title: str) -> None:
                from rich.columns import Columns
                op_panel = Panel.fit(body, title=title, border_style="cyan")
                if migration_warning:
                    _warn_title = migration_warning_title or "[bold yellow]⚠️  Upgrade Warning[/bold yellow]"
                    warn_panel = Panel(
                        migration_warning,
                        title=_warn_title,
                        border_style="yellow",
                        padding=(1, 2),
                    )
                    print(Columns([warn_panel, op_panel], equal=False, expand=True))
                else:
                    print(op_panel)
                print()

            # ── Derive keyed lists from op_classifications ────────────────────
            _is_cp4ba = (self._license_model or "") == "CP4BA"
            _mandatory_keys  = {'usage-metering'} | ({'licensing'} if _is_cp4ba else set())
            _upgrade_keys    = [k for k, c in _cls.items() if c == 'upgrade'   and k not in _mandatory_keys]
            _install_keys    = [k for k, c in _cls.items() if c == 'install'   and k not in _mandatory_keys]
            _current_keys    = [k for k, c in _cls.items() if c == 'current'   and k not in _mandatory_keys]
            _available_keys  = [k for k, c in _cls.items() if c == 'available' and k not in _mandatory_keys]

            # ── Detect migration type ──────────────────────────────────────────
            _legacy_types = {
                s.get('installation_type')
                for s in (operator_status or {}).values()
                if s.get('installation_type') in ('YAML', 'OLM')
            }
            _migration_src = " / ".join(sorted(_legacy_types)) if _legacy_types else None

            _has_existing = bool(_upgrade_keys or _current_keys or
                                 any(_cls_is(k, 'upgrade', 'current')
                                     for k in _mandatory_keys))

            if _has_existing:
                # ── UPGRADE / MIGRATION PANEL ─────────────────────────────────
                if _migration_src:
                    panel_lines = (
                        f"[bold cyan]IBM Content Assistant Operator Migration Plan "
                        f"({_migration_src} → Helm)[/bold cyan]\n\n"
                    )
                else:
                    panel_lines = "[bold cyan]Operator Upgrade / Install Plan[/bold cyan]\n\n"

                _mandatory_label = (
                    "[bold green]Mandatory (selectable in force mode):[/bold green]\n"
                    if force_mode else
                    "[bold green]Mandatory:[/bold green]\n"
                )
                panel_lines += _mandatory_label
                if _is_cp4ba:
                    panel_lines += _version_line('licensing',      'License Service Operator')
                panel_lines += _version_line('usage-metering', 'Usage Metering Operator')

                if _upgrade_keys or _install_keys:
                    if _migration_src:
                        panel_lines += f"\n[bold yellow]Migrating from {_migration_src} / Installing:[/bold yellow]\n"
                    else:
                        panel_lines += "\n[bold yellow]Upgrading / Installing:[/bold yellow]\n"
                    for k in _upgrade_keys:
                        panel_lines += _version_line(k, _display.get(k, k))
                    for k in _install_keys:
                        panel_lines += _version_line(k, _display.get(k, k))

                if _current_keys:
                    panel_lines += "\n[bold green]Already installed (no action needed):[/bold green]\n"
                    for k in _current_keys:
                        panel_lines += _version_line(k, _display.get(k, k))

                if _available_keys:
                    panel_lines += "\n[bold dim]Available to add (unchecked by default):[/bold dim]\n"
                    for k in _available_keys:
                        panel_lines += _version_line(k, _display.get(k, k))

                if _is_cp4ba:
                    _footer = (
                        "\n[dim]✱  License Service and Usage Metering are shown above; "
                        "in force mode they appear in the checkbox so you can include or exclude them.\n"
                        if force_mode else
                        "\n[dim]✱  License Service and Usage Metering are mandatory and deployed automatically when they need action.\n"
                    )
                else:
                    _footer = (
                        "\n[dim]✱  Usage Metering is shown above; "
                        "in force mode it appears in the checkbox so you can include or exclude it.\n"
                        if force_mode else
                        "\n[dim]✱  Usage Metering is mandatory and deployed automatically when it needs action.\n"
                        "✱  License Service is not required for non-CP4BA licenses.\n"
                    )

                _panel_title = (
                    f"[bold]Operator Migration ({_migration_src} → Helm)[/bold]"
                    if _migration_src else
                    "[bold]Operator Configuration[/bold]"
                )

            else:
                # ── FRESH-INSTALL PANEL ───────────────────────────────────────
                panel_lines = "[bold cyan]IBM Content Assistant Operator Installation Plan[/bold cyan]\n\n"
                if _is_cp4ba:
                    panel_lines += _version_line('licensing',      'License Service Operator')
                panel_lines += _version_line('usage-metering', 'Usage Metering Operator')
                if _in_release('content-assistant'):
                    panel_lines += _version_line('content-assistant', 'Content Assistant Operator')

                if _is_cp4ba:
                    _footer = "\n[dim]✱  License Service and Usage Metering are mandatory and always installed.\n"
                else:
                    _footer = (
                        "\n[dim]✱  Usage Metering is mandatory and always installed.\n"
                        "✱  License Service is not required for non-CP4BA licenses.\n"
                    )

                _panel_title = "[bold]Operator Configuration[/bold]"

            _footer += "\nSpace to toggle  •  ↑/↓ to move  •  Enter to confirm[/dim]"
            panel_lines += _footer

            _render_operator_panel(panel_lines, _panel_title)

            # ── Build checkbox ────────────────────────────────────────────────
            all_choices: list = []
            _listed: set = set()

            if force_mode:
                _force_mandatory = ('licensing', 'usage-metering') if _is_cp4ba else ('usage-metering',)
                for k in _force_mandatory:
                    if _in_release(k) and _cls_is(k, 'mandatory', 'upgrade', 'current'):
                        all_choices.append(questionary.Choice(
                            title=_display.get(k, k), value=k, checked=True
                        ))
                        _listed.add(k)

            # Upgrade / install — pre-checked
            for k in _upgrade_keys + _install_keys:
                if k not in _listed and _in_release(k):
                    all_choices.append(questionary.Choice(
                        title=_display.get(k, k), value=k, checked=True
                    ))
                    _listed.add(k)

            # Available (not installed, optional) — unchecked by default
            for k in _available_keys:
                if k not in _listed and _in_release(k):
                    all_choices.append(questionary.Choice(
                        title=_display.get(k, k), value=k, checked=False
                    ))
                    _listed.add(k)

            if not all_choices:
                # Nothing optional to select — mandatory operators will be auto-deployed.
                raw = []
            else:
                raw = questionary.checkbox(
                    "Select the operators to include in this deployment:",
                    choices=all_choices,
                    style=_checkbox_style,
                ).ask()
                raw = handle_cancelled_prompt(raw, "Operator selection cancelled by user")

            # ── Build selected_operators from raw checkbox result ─────────────
            self._selected_operators = []

            if not force_mode:
                # Auto-add mandatory operators whenever they need action OR are
                # classified as 'mandatory' (fresh install — they never reach
                # 'install' because deploy_operator.py marks them 'mandatory'
                # before the classification loop can set them to 'install').
                _auto_mandatory = ('licensing', 'usage-metering') if _is_cp4ba else ('usage-metering',)
                for k in _auto_mandatory:
                    if _cls_is(k, 'mandatory', 'upgrade', 'install'):
                        op_type = _key_to_type.get(k)
                        if op_type and op_type not in self._selected_operators:
                            self._selected_operators.append(op_type)

            for op_key in raw:
                op_type = _key_to_type.get(op_key)
                if op_type and op_type not in self._selected_operators:
                    self._selected_operators.append(op_type)

            self._logger.info(f"Operators configured: {[op.value for op in self._selected_operators]}")

            # ── Display final operator configuration ──────────────────────────
            print()

            status_key_map = {
                OperatorType.CONTENT_ASSISTANT: 'content-assistant',
                OperatorType.USAGE_METERING:    'usage-metering',
                OperatorType.LICENSE_ADVISOR:   'licensing',
            }

            def get_status_text(op_type):
                if operator_status:
                    status_key = status_key_map.get(op_type)
                    if status_key and status_key in operator_status:
                        op_status = operator_status[status_key]
                        if op_status.get('is_current', False):
                            if force_mode:
                                return f" [bold yellow](force redeploy {op_status.get('current_version', 'target')})[/bold yellow]"
                            return f" [dim](already at {op_status.get('current_version', 'target')} - install skipped)[/dim]"
                        elif op_status.get('installed', False):
                            return f" [yellow](upgrade from {op_status.get('current_version', 'unknown')})[/yellow]"
                return ""

            mandatory_types = (
                [OperatorType.LICENSE_ADVISOR, OperatorType.USAGE_METERING]
                if _is_cp4ba else
                [OperatorType.USAGE_METERING]
            )

            if force_mode:
                included_mandatory = [t for t in mandatory_types if t in self._selected_operators]
                excluded_mandatory = [t for t in mandatory_types if t not in self._selected_operators]
            else:
                included_mandatory = mandatory_types
                excluded_mandatory = []

            mandatory_ops = [get_operator_metadata(op) for op in included_mandatory]
            optional_ops  = [get_operator_metadata(op) for op in self._selected_operators
                             if op not in mandatory_types]

            display_text = "[bold cyan]Selected Operators[/bold cyan]\n\n"
            display_text += "[bold green]Mandatory Operators:[/bold green]\n"
            for op in mandatory_ops:
                op_type = next((t for t in included_mandatory
                                if get_operator_metadata(t).display_name == op.display_name), None)
                status_text = get_status_text(op_type) if op_type else ""
                display_text += f"  [green]✓[/green] {op.display_name}{status_text}\n"
            if excluded_mandatory:
                for t in excluded_mandatory:
                    m = get_operator_metadata(t)
                    display_text += f"  [dim]–  {m.display_name} (excluded by user)[/dim]\n"

            if optional_ops:
                display_text += "\n[bold yellow]Optional Operators:[/bold yellow]\n"
                for op in optional_ops:
                    op_type = next((t for t in self._selected_operators
                                    if get_operator_metadata(t).display_name == op.display_name), None)
                    status_text = get_status_text(op_type) if op_type else ""
                    display_text += f"  [green]✓[/green] {op.display_name}{status_text}\n"

            operators_to_deploy = 0
            operators_to_skip   = 0
            if operator_status:
                for op_type in self._selected_operators:
                    status_key = status_key_map.get(op_type)
                    if status_key and status_key in operator_status:
                        if operator_status[status_key].get('is_current', False) and not force_mode:
                            operators_to_skip += 1
                        else:
                            operators_to_deploy += 1
                    else:
                        operators_to_deploy += 1
            else:
                operators_to_deploy = len(self._selected_operators)

            if operators_to_skip > 0:
                display_text += f"\n[dim]Total: {operators_to_deploy} operator(s) will be deployed, {operators_to_skip} skipped (already current)[/dim]"
            else:
                display_text += f"\n[dim]Total: {operators_to_deploy} operator(s) will be deployed[/dim]"

            print(Panel.fit(
                display_text,
                style="cyan",
                title="[bold]Deployment Configuration[/bold]"
            ))
            print()

            if operators_to_deploy == 0:
                print(Panel.fit(
                    "[bold green]✓ Nothing to Deploy[/bold green]\n\n"
                    "All selected operators are already at the target version.\n"
                    "No deployment is needed.\n\n"
                    "[dim]Use --force to redeploy anyway.[/dim]",
                    title="[bold green]✓ System Up to Date[/bold green]",
                    border_style="green"
                ))
                print()
                raise typer.Exit(code=0)

        except typer.Exit:
            raise
        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_operator_type function - {str(e)}")
            raise

    def collect_airgap_configuration(self) -> dict:
        """
        Collect airgap/connectivity configuration for the deployment.

        Asks whether this is an airgapped (offline) deployment.  For airgapped
        deployments the user selects between a mirror-config and a private registry;
        for connected deployments the IBM Entitlement Key is collected and validated.

        Returns:
            dict with keys:
                is_airgapped (bool)
                use_mirror_config (bool)
                use_private_registry (bool)
                enable_software_central (bool)
                entitlement_key (str)
                private_registry_details (dict)
        """
        try:
            self._logger.info("Collecting airgap deployment configuration")

            airgap_config = {
                'is_airgapped': False,
                'use_mirror_config': False,
                'use_private_registry': False,
                'enable_software_central': False,
                'entitlement_key': '',
                'private_registry_details': {},
            }

            if self._silent_mode:
                # Silent mode: build config from already-collected private-registry state
                if self._private_registry and self._private_registry_valid:
                    airgap_config['is_airgapped'] = True
                    airgap_config['use_private_registry'] = True
                    airgap_config['enable_software_central'] = False
                    airgap_config['private_registry_details'] = {
                        'host':        self._private_registry_host,
                        'port':        self._private_registry_port,
                        'username':    self._private_registry_username,
                        'password':    self._private_registry_password,
                        'ssl_enabled': self._private_registry_ssl_enabled,
                        'ssl_cert':    self._private_registry_ssl_cert,
                        'full_server': self._private_registry_full_server,
                        'path':        self._private_registry_path,
                        'validated':   self._private_registry_valid,
                    }
                else:
                    airgap_config['enable_software_central'] = bool(self._entitlement_key)
                    airgap_config['entitlement_key'] = self._entitlement_key or ''
                self._airgap_config = airgap_config
                self._logger.info(f"Airgap configuration (silent): {airgap_config}")
                return airgap_config

            # ── Interactive mode ──────────────────────────────────────────────
            airgap_info = (
                "[bold cyan]🌐 Deployment Environment Configuration[/bold cyan]\n\n"
                "Determines how container images are accessed and whether license/usage\n"
                "data is uploaded automatically to IBM Software Central.\n\n"
                "[bold yellow]Airgapped:[/bold yellow] no internet access — images served from mirror or private registry.\n"
                "  Software Central upload [bold red]disabled[/bold red]; data must be uploaded manually.\n\n"
                "[bold yellow]Connected:[/bold yellow] pulls images from IBM Entitled Registry directly.\n"
                "  Software Central upload [bold green]enabled[/bold green] automatically.\n\n"
                "[dim]Override Helm chart source: [cyan]--helm-chart-source <github|packaged|local|public|url>[/cyan][/dim]"
            )
            print(Panel(airgap_info, title="[bold white]Deployment Environment[/bold white]",
                        border_style="cyan", padding=(1, 2)))
            print()

            is_airgapped = questionary.confirm(
                "Is this an airgapped (offline) deployment?",
                default=False,
                style=Style([
                    ('qmark',    'fg:cyan bold'),
                    ('question', 'bold'),
                    ('answer',   'fg:cyan bold'),
                ])
            ).ask()
            is_airgapped = handle_cancelled_prompt(is_airgapped, "Deployment configuration cancelled by user")
            airgap_config['is_airgapped'] = is_airgapped
            self._logger.info(f"Deployment is airgapped: {is_airgapped}")

            if is_airgapped:
                print()
                image_source = questionary.select(
                    "How are container images being provided?",
                    choices=[
                        questionary.Choice(
                            title="Mirror Configuration  (oc-mirror or similar tool)",
                            value="mirror"
                        ),
                        questionary.Choice(
                            title="Private Registry  (pull from a private container registry)",
                            value="registry"
                        ),
                    ],
                    style=Style([
                        ('qmark',       'fg:cyan bold'),
                        ('question',    'bold'),
                        ('answer',      'fg:cyan bold'),
                        ('pointer',     'fg:cyan bold'),
                        ('highlighted', 'fg:cyan bold'),
                    ])
                ).ask()
                image_source = handle_cancelled_prompt(image_source, "Image source selection cancelled by user")

                if image_source == "mirror":
                    airgap_config['use_mirror_config'] = True
                    self._logger.info("Using mirror configuration for airgapped deployment")
                    print()
                    print(Panel.fit(
                        "✓ Mirror configuration selected\n\n"
                        "Software Central upload will be [bold red]disabled[/bold red].\n"
                        "[yellow]Note:[/yellow] License and usage data must be uploaded manually.",
                        style="green"
                    ))
                else:
                    airgap_config['use_private_registry'] = True
                    self._logger.info("Using private registry for airgapped deployment")
                    self.collect_verify_private_registry()
                    airgap_config['private_registry_details'] = {
                        'host':        self._private_registry_host,
                        'port':        self._private_registry_port,
                        'username':    self._private_registry_username,
                        'password':    self._private_registry_password,
                        'ssl_enabled': self._private_registry_ssl_enabled,
                        'ssl_cert':    self._private_registry_ssl_cert,
                        'full_server': self._private_registry_full_server,
                        'path':        self._private_registry_path,
                        'validated':   self._private_registry_valid,
                    }
                    print()
                    print(Panel.fit(
                        "✓ Private registry validated\n\n"
                        "Software Central upload will be [bold red]disabled[/bold red].\n"
                        "[yellow]Note:[/yellow] License and usage data must be uploaded manually.",
                        style="green"
                    ))

                airgap_config['enable_software_central'] = False

            else:
                # Connected deployment — collect and validate IBM Entitlement Key
                print()
                print(Panel.fit(
                    "[bold green]Connected Deployment[/bold green]\n\n"
                    "IBM Entitlement Key required to access the IBM Entitled Registry.",
                    style="green"
                ))
                self.collect_verify_entitlement_key()
                if self._entitlement_key_valid:
                    airgap_config['entitlement_key'] = self._entitlement_key
                    airgap_config['enable_software_central'] = True
                    self._logger.info("Successfully authenticated with IBM Entitled Registry")
                    print()
                    print(Panel.fit(
                        "✓ IBM Entitlement Key validated\n\n"
                        "Software Central upload will be [bold green]enabled[/bold green].",
                        style="green"
                    ))
                else:
                    self._logger.error("Failed to validate IBM Entitlement Key")
                    print()
                    print(Panel.fit(
                        "❌ IBM Entitlement Key validation failed\n\n"
                        "Cannot proceed without valid credentials.",
                        style="bold red"
                    ))
                    raise typer.Exit(code=1)

            self._airgap_config = airgap_config
            self._logger.info(f"Airgap configuration completed: {airgap_config}")
            return airgap_config

        except typer.Exit:
            raise
        except Exception as e:
            self._logger.exception(f"Exception in collect_airgap_configuration: {str(e)}")
            raise

    # Create a function to gather platform from user
    def collect_platform(self):
        try:
            self._logger.info("Collecting Platform details")
            print()
            result = questionary.select(
                "Select a Platform Type:",
                choices=[
                    questionary.Choice("OCP",  value="OCP"),
                    questionary.Choice("CNCF", value="CNCF"),
                ],
                style=Style([
                    ('qmark',       'fg:cyan bold'),
                    ('question',    'bold'),
                    ('answer',      'fg:cyan bold'),
                    ('pointer',     'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('selected',    'fg:green bold'),
                ])
            ).ask()
            result = handle_cancelled_prompt(result, "Platform selection cancelled by user")
            self._platform = result
            self._logger.info(f"Platform selected: {self._platform}")
        except Exception as e:
            self._logger.exception(
                f"Exception from utility script in collect_platform function -  {str(e)}")

    def __parse_optional_components__(self, choices=None):
        try:
            components = set()
            if choices is None:
                print("No optional components chosen")
            else:
                # loop through choices and add to optional components list based on Enum value
                for choice in choices:
                    components.add(self.OptionalComponents(choice).name)

            self._components =  list(components)

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in set_optional_components function -  {str(e)}")

        # Create a function to gather optional components from the user
    def collect_mustgather_components(self, component_list):
        try:
            # Convert component list to enum values (only genai_connector is valid)
            valid_components = []
            for component in component_list:
                try:
                    valid_components.append(self.OptionalComponents[component].value)
                except KeyError:
                    self._logger.info(f"Ignoring unknown component: {component}")
            choices = set(valid_components)

            print()

            # Component selection panel
            component_info = Text()
            component_info.append("In addition to the deployment artifacts, the MustGather can collect component-specific logs and configuration files.\n\n", style="white")
            component_info.append("📦 ", style="bold cyan")
            component_info.append("Collected Data Includes:\n", style="bold white")
            component_info.append("  • Component Logs\n", style="white")
            component_info.append("  • Component Version\n", style="white")
            component_info.append("  • Python Version\n", style="white")

            print(Panel(
                component_info,
                title="[bold white]Deployed Components[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            # IBM Content Assistant components
            cas_components = [
                {'name': 'GenAI Connector (Content Assistant)', 'value': 1},
            ]

            print()
            print(Panel.fit(
                "[bold cyan]Content Assistant Components[/bold cyan]\n\n"
                "Select which components to collect logs for.",
                style="cyan",
                title="[bold]IBM Content Assistant[/bold]"
            ))
            print()

            result = questionary.checkbox(
                "Select components (use space to select, enter to confirm):",
                choices=cas_components,
                style=Style([
                    ('selected', 'fg:green bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan'),
                    ('answer', 'fg:green bold'),
                    ('checkbox', 'fg:cyan bold'),
                    ('checkbox-selected', 'fg:green bold')
                ])
            ).ask()

            result = handle_cancelled_prompt(result, "Component selection cancelled by user")
            self.__parse_optional_components__(set(result))

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in collect_mustgather_components function -  {str(e)}")

    def collect_sensitive_data(self, collect=None):
        try:
            if collect is None:
                print()
                print(Panel.fit("Collect Sensitive Data"))
                print()
                print("The IBM Content Assistant MustGather would like to collect sensitive configuration data to help diagnose and troubleshoot issues.\n"
                      "This includes configuration files, logs and secrets with unencrypted values.")
                print()

                self._sensitive_collect = Confirm.ask("Do you want to collect sensitive data?")
            else:
                self._sensitive_collect = collect
        except Exception as e:
            self._logger.exception(
                f"Exception from utility script in collect_sensitive_data function -  {str(e)}")


    def collect_namespace(self, namespace=None):
        # namespace parameter is none when silent mode is NOT selected, hence the conditions to skip conditions if silent mode is selected
        try:
            self._logger.info("Gathering namespace information")
            if namespace is None:
                try:
                    self._current_namespace = self._k.current_namespace
                    self._logger.info(f"Current namespace from kubeconfig: {self._current_namespace}")
                except Exception as e:
                    self._current_namespace = None
                    self._logger.info("Gathering namespace information failed")


            # Standard invalid namespaces for both OCP and CNCF platforms
            invalid_namespaces = ["services", "default", "calico-system", "ibm-cert-store", "ibm-observe",
                                  "ibm-system", "ibm-odf-validation-webhook"]
            invalid_namespace_to_start_with = ["openshift-", "kube-"]

            while True:
                if namespace is None:
                    # Enhanced namespace prompt with context
                    namespace_info = Text()
                    namespace_info.append("📦 Kubernetes Namespace Configuration\n\n", style="bold cyan")
                    namespace_info.append("The namespace isolates your IBM Content Assistant deployment resources.\n", style="white")
                    if self._current_namespace:
                        namespace_info.append(f"\n💡 Current namespace detected: ", style="yellow")
                        namespace_info.append(f"{self._current_namespace}", style="bold green")

                    # Add informational note about ibm-licensing namespace for license service.
                    # Only shown when a CP4BA license is selected — that is the only case where
                    # the License Service operator (and therefore ibm-licensing namespace) is deployed.
                    _will_deploy_license_service = (
                        self._script_type == "deploy"
                        and self._license_model == "CP4BA"
                    )
                    if _will_deploy_license_service:
                        namespace_info.append("\n\n", style="white")
                        namespace_info.append("⚠️  IMPORTANT: ", style="bold yellow")
                        namespace_info.append("The ", style="white")
                        namespace_info.append("ibm-licensing", style="yellow")
                        namespace_info.append(" namespace will be created and used for the IBM License Service operator.\n", style="white")
                        namespace_info.append("   This is ", style="white")
                        namespace_info.append("required", style="bold white")
                        namespace_info.append(" for license management and compliance tracking.", style="white")

                    print(Panel(
                        namespace_info,
                        title="[bold white]Namespace Selection[/bold white]",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    print()

                    answer = questionary.text(
                        "Enter your namespace:",
                        default=self._current_namespace if self._current_namespace else "",
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()

                    # Handle cancellation
                    answer = handle_cancelled_prompt(answer, "Namespace selection cancelled by user")
                    if self._script_type != "deploy":
                        namespace_exists = self._k.check_namespace_exists(namespace=answer)
                        if not namespace_exists:
                            print()
                            print(Panel.fit(f"Namespace '{answer}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            continue
                else:
                    # silent install check for namespace will not loop more than once if invalid namespace is provided
                    if self._script_type != "deploy":
                        self._logger.info(f"Checking if namespace: {namespace} exists.")
                        namespace_exists = self._k.check_namespace_exists(namespace=namespace)
                        if not namespace_exists:
                            self._logger.info(f"Namespace '{namespace}' does not exist.")
                            print()
                            print(Panel.fit(f"Namespace '{namespace}' does not exist.\n"
                                            f"Enter a valid namespace for script to proceed.", style="bold red"))
                            print()
                            exit(1)
                    answer = namespace

                answer = answer.strip()
                # Start of namespace validation
                # Check if the answer is not empty after stripping whitespace
                if answer == '':
                    self._logger.debug(f"Namespace cannot be empty. Please try again")
                    print()
                    print("[prompt.invalid]Namespace cannot be empty. Please try again")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if the answer is not in the list of invalid namespaces
                if any(answer in value for value in invalid_namespaces):
                    invalid_msg = ""
                    for value in invalid_namespaces:
                        invalid_msg += f"- {value}\n"
                    invalid_msg.strip()

                    print()
                    print(f"[prompt.invalid]Namespace cannot be any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot be any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                if any(answer.startswith(value) for value in invalid_namespace_to_start_with):
                    invalid_msg = ""
                    for value in invalid_namespace_to_start_with:
                        invalid_msg += f"- {value}\n"
                    invalid_msg = invalid_msg.strip()
                    print()
                    print(
                        f"[prompt.invalid]Namespace cannot start with any of the following. Please try again.\n{invalid_msg}")
                    print()
                    self._logger.debug(f"Namespace cannot start with any of the following: {invalid_msg}")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is only numbers
                if answer.isnumeric():
                    print()
                    print("[prompt.invalid]Namespace cannot be a number. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if the answer has any uppercase letters
                if any(char.isupper() for char in answer):
                    print()
                    print("[prompt.invalid]Namespace cannot contain uppercase letters. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot contain uppercase letters. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace is more than 1 word
                if " " in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain spaces. Use '-'. Please try again.")
                    print()
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # Check if namespace has an underscore
                if "_" in answer:
                    print()
                    print("[prompt.invalid]Namespace cannot contain '_'. Use '-'. Please try again.")
                    print()
                    self._logger.debug(f"Namespace cannot be a number. Please try again.")
                    if namespace is None:
                        continue
                    else:
                        exit(0)

                # for all scripts using this function other than deploy operator we need to check if namespace exists
                self._namespace = answer
                self._logger.info(f"Namespace entered: {self._namespace}")
                break

        except Exception as e:
            self._logger.exception(
                f"Exception from gathering deployment details in collect namespace function -  {str(e)}")

    # Create a function to gather license model details
    def collect_license_model(self, version_data, license_accept=None, license_type=None):
        try:
            self._logger.info("Gathering license model details")

            # Handle None version_data gracefully
            if version_data is None:
                product_version = '1.0.0'
                app_version = '1.0.0'
            else:
                # VERSION drives Helm installs and UI display
                product_version = version_data.get("VERSION", '1.0.0').split('-')[0]
                # APP_VERSION drives CR template directory selection
                app_version = version_data.get("APP_VERSION", product_version).split('-')[0]
            self._cas_version = app_version
            self._logger.info(f"IBM Content Assistant product version: {product_version}, CR template version (APP_VERSION): {app_version}")

            if license_accept is None:
                # First Panel: License Agreement Required with version and URLs
                license_info_text = Text()
                license_info_text.append("🔍 ", style="bold yellow")
                license_info_text.append("Detected Version: ", style="bold white")
                license_info_text.append(f"{product_version}\n\n", style="bold green")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("International Program License Agreement\n\n", style="bold white")

                license_info_text.append("Please review the license agreements before proceeding:\n\n", style="white")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("IBM Content Assistant:\n", style="bold white")
                license_info_text.append("   https://ibm.biz/CPE_CCX_License_26_0_0\n\n", style="cyan")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("Software Notices:\n", style="bold white")
                license_info_text.append("   http://ibm.biz/CCX_Notices_26_0_0\n\n", style="cyan")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("IBM Enterprise Records:\n", style="bold white")
                license_info_text.append("   https://ibm.biz/ier_license_521\n\n", style="cyan")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("IBM Content Collector for SAP:\n", style="bold white")
                license_info_text.append("   https://ibm.biz/iccsap_license_4002\n\n", style="cyan")

                license_info_text.append("📄 ", style="bold cyan")
                license_info_text.append("IBM Cloud Pak for Business Automation:\n", style="bold white")
                license_info_text.append("   https://ibm.biz/cp4ba_license_2600\n\n", style="cyan")

                license_info_text.append("⚠ ", style="bold yellow")
                license_info_text.append("You must accept the license to continue deployment.", style="bold yellow")

                print(Panel(
                    license_info_text,
                    title="[bold white]License Agreement Required[/bold white]",
                    border_style="white",
                    padding=(1, 2)
                ))
                print()

                # Second Panel: Data Collection Notice
                agreement_text = Text()
                agreement_text.append("⚠ ", style="bold yellow")
                agreement_text.append("You are about to accept the IBM Content Assistant License Agreement\n\n", style="bold white")

                agreement_text.append("📊 ", style="bold cyan")
                agreement_text.append("Data collection will be enabled by default\n", style="white")
                agreement_text.append("📄 ", style="bold cyan")
                agreement_text.append("Review full license terms in the License Information document\n\n", style="white")

                agreement_text.append("By accepting the license, you agree and understand that by default the program collects certain data and metrics regarding deployment and usage. ", style="white")
                agreement_text.append("For more information, please consult the License Information for IBM Content Assistant.", style="bold white")

                print(Panel(
                    agreement_text,
                    title="[bold yellow]⚠ LICENSE AGREEMENT REQUIRED ⚠[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2)
                ))
                print()

                # Third Panel: License Terms
                terms_text = Text()
                terms_text.append("📋 ", style="bold cyan")
                terms_text.append("License Agreement Acceptance\n\n", style="bold white")

                terms_text.append("By accepting, you agree to:\n", style="white")
                terms_text.append("  • Comply with all license terms and conditions\n", style="white")
                terms_text.append("  • Use the software within entitled scope\n", style="white")
                terms_text.append("  • Maintain proper license documentation\n\n", style="white")

                terms_text.append("⚠ ", style="bold yellow")
                terms_text.append("Required: ", style="bold yellow")
                terms_text.append("You must accept to proceed with deployment.", style="white")

                print(Panel(
                    terms_text,
                    title="[bold white]License Terms[/bold white]",
                    border_style="white",
                    padding=(1, 2)
                ))
                print()

                self._accept_license = questionary.confirm(
                    "Do you accept the IBM Content Assistant License Agreement?",
                    default=False,
                    style=Style([
                        ('qmark', 'fg:yellow bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:green bold'),
                    ])
                ).ask()

                # Handle cancellation
                self._accept_license = handle_cancelled_prompt(self._accept_license, "License acceptance cancelled by user")
            else:
                self._accept_license = license_accept

            if not self._accept_license:
                self._logger.debug("International Program License is not accepted. You must accept the International Program License to continue.")
                print("\n[prompt.invalid]You must accept the International Program License to continue.")
                exit(1)

            self._logger.info("International Program License is accepted.")

            # ── License type selection ────────────────────────────────────────
            # Ask whether the customer is using an Essentials or CP4BA license.
            # This determines whether the License Service operator is required.
            # In silent mode, license_type is provided directly; skip prompts.
            if license_type is not None:
                self._license_model = license_type
                self._logger.info(f"License model set from silent config: {self._license_model!r}")
            else:
                license_type_info = Text()
                license_type_info.append("🏷️ License Type Selection\n\n", style="bold cyan")
                license_type_info.append("Choose the license model that matches your entitlement:\n\n", style="white")
                license_type_info.append("  • ", style="cyan")
                license_type_info.append("Content Cortex Essentials", style="bold green")
                license_type_info.append(
                    " - IBM Content Cortex Essentials license\n"
                    "    Requires: Usage Metering only\n\n",
                    style="white"
                )
                license_type_info.append("  • ", style="cyan")
                license_type_info.append("Content Cortex Premium", style="bold green")
                license_type_info.append(
                    " - IBM Content Cortex Premium license\n"
                    "    Requires: Usage Metering only\n\n",
                    style="white"
                )
                license_type_info.append("  • ", style="cyan")
                license_type_info.append("CP4BA", style="bold green")
                license_type_info.append(
                    " - Cloud Pak for Business Automation license\n"
                    "    Requires: License Service + Usage Metering\n",
                    style="white"
                )

                print(Panel(
                    license_type_info,
                    title="[bold white]License Model Configuration[/bold white]",
                    border_style="cyan",
                    padding=(1, 2)
                ))
                print()

                license_type_result = questionary.select(
                    "Select a License Type:",
                    choices=[
                        questionary.Choice("Essentials", value="Essentials"),
                        questionary.Choice("Premium",    value="Premium"),
                        questionary.Choice("CP4BA",      value="CP4BA"),
                    ],
                    style=Style([
                        ('qmark',       'fg:cyan bold'),
                        ('question',    'bold'),
                        ('answer',      'fg:cyan bold'),
                        ('pointer',     'fg:cyan bold'),
                        ('highlighted', 'fg:cyan'),
                        ('selected',    'fg:green bold'),
                    ])
                ).ask()

                license_type_result = handle_cancelled_prompt(license_type_result, "License type selection cancelled by user")
                self._license_model = license_type_result  # "Essentials", "Premium", or "CP4BA"
                self._logger.info(f"License model selected: {self._license_model!r}")

        except Exception as e:
            self._logger.exception(
                f"Exception from gather script in license model function -  {str(e)}")

    # Function to collect and validate the entitlement key
    def collect_verify_entitlement_key(self):
        try:
            self._logger.info("Collecting and validating the IBM Entitlement Registry key")

            # Enhanced entitlement key info panel
            entitlement_info = Text()
            entitlement_info.append("🔑 IBM Entitlement Registry Key\n\n", style="bold cyan")
            entitlement_info.append("The entitlement key provides access to IBM container images from the IBM Entitled Registry.\n\n", style="white")
            entitlement_info.append("What you need:\n", style="bold yellow")
            entitlement_info.append("  • Valid IBM Entitlement Registry key\n", style="white")
            entitlement_info.append("  • Associated with your IBM ID\n", style="white")
            entitlement_info.append("  • Proper entitlements for IBM Content Assistant\n\n", style="white")

            entitlement_key_kc = Text(
                "https://www.ibm.com/docs/SSSUG3T_1.0.0/com.ibm.icacm.install/icacm_topics/tsk_images_enterp_entitled.html",
                style="link https://www.ibm.com/docs/SSSUG3T_1.0.0/com.ibm.icacm.install/icacm_topics/tsk_images_enterp_entitled.html")
            entitlement_info.append("📖 Documentation: ", style="bold yellow")
            entitlement_info.append(entitlement_key_kc)

            print(Panel(
                entitlement_info,
                title="[bold white]Entitlement Key Configuration[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            if not self._silent_mode:
                self._entitlement_key_present = questionary.confirm(
                    "Do you have an IBM Entitlement Registry key?",
                    default=True,
                    style=Style([
                        ('qmark', 'fg:cyan bold'),
                        ('question', 'bold'),
                        ('answer', 'fg:cyan bold'),
                    ])
                ).ask()
                self._entitlement_key_present = handle_cancelled_prompt(
                    self._entitlement_key_present, "Operation cancelled by user"
                )

                # For the loadimages script the entitlement key is mandatory
                if self._script_type.lower() == "load_extract" and not self._entitlement_key_present:
                    print()
                    print(Panel.fit(
                        "[red]An IBM Entitlement Key is required to pull images.\n"
                        "Configure an IBM Entitlement Key and re-run the script[/red]",
                        border_style="red"
                    ))
                    exit()
            # For silent mode we have the entitlement key present so we can set this variable to true
            else:
                self._entitlement_key_present = True
            if not self._entitlement_key_present:
                if not self._silent_mode:
                    self.collect_verify_private_registry()
            else:
                while True:
                    # No need to ask for an entitlement key if silent install is enabled
                    if not self._silent_mode:
                        print()
                        answer = questionary.password(
                            "Enter your IBM Entitlement Registry key:",
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()
                        answer = handle_cancelled_prompt(answer, "IBM Entitlement Registry key entry cancelled by user")

                        if ':' in answer:
                            username = answer.split(':')[0]
                            password = answer.split(':')[1]
                            self._entitlement_key = password
                        else:
                            username = "cp"
                            self._entitlement_key = answer
                    else:
                        username = "cp"

                    if not self._entitlement_key:
                        print()
                        print(Panel.fit("[red]IBM Entitlement Registry key cannot be empty. Please try again.[/red]", border_style="red"))
                        self._logger.debug(f"IBM Entitlement Registry key cannot be empty. Please try again.")
                        continue
                    else:
                        self._logger.info("Collected IBM Entitlement Registry key.")
                        # Use HTTP-based authentication (no podman required)
                        try:
                            registry_config = RegistryConfig.from_url(
                                url=f"https://{self._registry}",
                                tls_verify=False
                            )
                            credentials = RegistryCredentials(
                                username=username,
                                password=self._entitlement_key
                            )
                            authenticator = RegistryAuthenticator(registry_config, credentials, self._logger)
                            auth_result = authenticator.authenticate_http()
                            self._entitlement_key_valid = auth_result.success
                        except Exception as e:
                            self._logger.error(f"HTTP authentication failed: {e}")
                            self._entitlement_key_valid = False

                    if not self._entitlement_key_valid:
                        print()
                        self._logger.debug(f"IBM Entitlement key could not be validated.")
                        print(Panel.fit("[red]IBM Entitlement key could not be validated. Please try again.[/red]", border_style="red"))
                        if not self._silent_mode:
                            continue
                        else:
                            exit()

                    break

                self._logger.info("Successfully authenticated with IBM Entitled Registry")
                msg_panel = Panel.fit("Successfully authenticated with IBM Entitled Registry", style="bold green")
                print()
                print(msg_panel)

        except Exception as e:
            self._logger.exception(
                f"Exception from gather Class in entitlement key function -  {str(e)}")

    # Function to collect and validate private registry details
    # This function is used for script type load_extract and deploy_operator

    def verify_private_registry(self):
        if not self._silent_mode:
            while True:
                while True:
                    print()
                    self._private_registry_username = questionary.text(
                        "Enter the private registry username:",
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    self._private_registry_username = handle_cancelled_prompt(self._private_registry_username, "Private registry username entry cancelled by user")
                    if self._private_registry_username == "":
                        print()
                        print("[prompt.invalid]Private registry Username can't be empty. Please try again.")
                        self._logger.debug(f"Private registry username cannot be empty. Please try again.")
                    else:
                        break

                while True:
                    print()
                    self._private_registry_password = questionary.password(
                        "Enter the private registry password:",
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()
                    self._private_registry_password = handle_cancelled_prompt(self._private_registry_password, "Private registry password entry cancelled by user")
                    if self._private_registry_password == "":
                        print()
                        print("[prompt.invalid]Private registry password can't be empty. Please try again.")
                        self._logger.debug(f"Private registry password cannot be empty. Please try again.")
                    else:
                        break

                # Use HTTP-based authentication (no podman required)
                try:
                    scheme = "https" if self._private_registry_ssl_enabled else "http"
                    registry_url = f"{scheme}://{self._private_registry_host}:{self._private_registry_port}"
                    registry_config = RegistryConfig.from_url(
                        url=registry_url,
                        tls_verify=self._tls_verify,
                        ssl_cert_path=Path(self._private_registry_ssl_cert) if self._private_registry_ssl_enabled and self._tls_verify and self._private_registry_ssl_cert else None
                    )
                    credentials = RegistryCredentials(
                        username=self._private_registry_username,
                        password=self._private_registry_password
                    )
                    authenticator = RegistryAuthenticator(registry_config, credentials, self._logger)
                    auth_result = authenticator.authenticate_http()
                    self._private_registry_valid = auth_result.success
                except Exception as e:
                    self._logger.error(f"HTTP authentication failed: {e}")
                    self._private_registry_valid = False

                if not self._private_registry_valid:
                    print()
                    print("[prompt.invalid]Private registry credentials could not be authenticated. Please try again")
                    self._logger.debug(f"Private registry credentials could not be authenticated. Please try again.")
                    if not self._silent_mode:
                        continue
                    else:
                        exit()

                msg = "Successfully Authenticated with Private Registry"
                self._private_registry = True
                if self._private_registry_ssl_enabled:
                    msg = f"{msg} over SSL"
                self._logger.info(f"{msg}")
                msg_panel = Panel.fit(msg, style="bold green")
                print()
                print(msg_panel)

                break

        else:
            # Use HTTP-based authentication (no podman required)
            try:
                # Authentication is always against the base registry (hostname:port).
                # The path component (e.g. /myns) is part of the image reference only
                # and must NOT be included here — including it causes HTTP 400 on most
                # registries because <host>/myns/v2/ is not a valid registry API path.
                scheme = "https" if self._private_registry_ssl_enabled else "http"
                registry_url = f"{scheme}://{self._private_registry_host}:{self._private_registry_port}"
                registry_config = RegistryConfig.from_url(
                    url=registry_url,
                    tls_verify=self._tls_verify,
                    ssl_cert_path=Path(self._private_registry_ssl_cert) if self._private_registry_ssl_enabled and self._tls_verify and self._private_registry_ssl_cert else None
                )
                credentials = RegistryCredentials(
                    username=self._private_registry_username,
                    password=self._private_registry_password
                )
                authenticator = RegistryAuthenticator(registry_config, credentials, self._logger)
                auth_result = authenticator.authenticate_http()
                self._private_registry_valid = auth_result.success
            except Exception as e:
                self._logger.error(f"HTTP authentication failed: {e}")
                self._private_registry_valid = False

            if not self._private_registry_valid:
                print()
                print("[prompt.invalid]Private registry credentials could not be authenticated. Please try again")
                self._logger.debug(f"Private registry credentials could not be authenticated. Please try again.")
                exit(1)

            msg = "Successfully authenticated with Private Registry"
            self._private_registry = True
            if self._private_registry_ssl_enabled:
                msg = f"{msg} over SSL"
            self._logger.info(f"{msg}")
            msg_panel = Panel.fit(msg, style="bold green")
            print()
            print(msg_panel)

    def collect_verify_private_registry(self, skip_validation_panel=False):
        try:
            self._logger.info("Collecting and validating the Private registry")

            # Menu based logic required only for silent mode
            if not self._silent_mode:
                while True:
                    # Different menu questions for the script type
                    # Skip validation panel if already shown in airgap flow
                    if self._script_type == "load_extract" and not skip_validation_panel:
                        print()
                        validation_info = Text()
                        validation_info.append("📦 Private Registry Validation\n\n", style="bold cyan")
                        validation_info.append("A private image registry must be used to store all images used in an offline (airgap) deployment.\n\n", style="white")
                        validation_info.append("Before proceeding, ensure you have:\n", style="bold yellow")
                        validation_info.append("  • Access to a private registry\n", style="white")
                        validation_info.append("  • Sufficient storage space for all images\n", style="white")
                        validation_info.append("  • Network connectivity to the registry\n", style="white")

                        print(Panel(
                            validation_info,
                            title="[bold white]Registry Access Check[/bold white]",
                            border_style="cyan",
                            padding=(1, 2)
                        ))
                        print()

                        self._private_registry_ready = questionary.confirm(
                            "Do you have access to a private registry where you can store images?",
                            default=True,
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()
                        handle_cancelled_prompt(self._private_registry_ready, "Operation cancelled by user")
                        if not self._private_registry_ready:
                            print()
                            print(
                                "[prompt.invalid]A Private Registry is required to store images.\n"
                                "Configure a Private Registry and re-run the script")
                            exit(1)
                    elif self._script_type == "deploy" and not skip_validation_panel:
                        # Private registry is required for air-gapped deployments
                        print()
                        validation_info = Text()
                        validation_info.append("✅ Validate Private Registry\n\n", style="bold cyan")
                        validation_info.append("A private image registry must be used to store all images in your local environment.\n", style="white")
                        validation_info.append("Please ensure that all required images are mirrored to the private registry before proceeding.\n\n", style="white")
                        validation_info.append("📖 For more information, see: ", style="bold yellow")
                        validation_link = Text(
                            "https://www.ibm.com/docs/en/content-assistant",
                            style="link https://www.ibm.com/docs/en/content-assistant"
                        )
                        validation_info.append(validation_link)

                        print(Panel(
                            validation_info,
                            title="[bold white]Image Mirroring Verification[/bold white]",
                            border_style="cyan",
                            padding=(1, 2)
                        ))
                        print()

                        self._private_registry_ready = questionary.confirm(
                            "Have you mirrored all required images to a private registry?",
                            default=True,
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()
                        handle_cancelled_prompt(self._private_registry_ready, "Operation cancelled by user")

                    # If validation panel was skipped, set ready to True (already confirmed in airgap flow)
                    if skip_validation_panel:
                        self._private_registry_ready = True
                        if not self._private_registry_ready:
                            print()
                            print("[prompt.invalid]Use load_images.py to push operator images to a private registry and re-run the script")
                            print(Panel.fit(Syntax("python3 load_images.py", "python")))
                            exit(1)
                    # For the deploy script the prompt was already shown above — just print the
                    # informational reminder text (no second confirm) so the user sees the context
                    # before being asked for the registry URL.
                    elif self._script_type == "deploy" and not skip_validation_panel:
                        private_registry_kc = Text(
                            "https://www.ibm.com/docs/en/content-assistant",
                            style="link https://www.ibm.com/docs/en/content-assistant")
                        print()
                        print(f"A private image registry must be used to store all images in your local environment.\n"
                            f"Please ensure that all required images are mirrored to the private registry before proceeding.\n\n"
                            f"For more information, see {private_registry_kc}.")
                    # Only ask about mirrored images for scripts other than deploy and load_extract.
                    # The deploy script already asked at the panel above (lines 1661-1669),
                    # so asking again here would duplicate the prompt.
                    elif self._script_type not in ("deploy", "load_extract"):
                        private_registry_kc = Text(
                            "https://www.ibm.com/docs/en/content-assistant",
                            style="link https://www.ibm.com/docs/en/content-assistant")
                        print()
                        print(f"A private image registry must be used to store all images in your local environment.\n"
                            f"Please ensure that all required images are mirrored to the private registry before proceeding.\n\n"
                            f"For more information, see {private_registry_kc}.")
                        print()
                        self._private_registry_ready = questionary.confirm(
                            "Have you mirrored all required images to a private registry?",
                            default=True,
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()
                        handle_cancelled_prompt(self._private_registry_ready, "Operation cancelled by user")
                        if not self._private_registry_ready:
                            print()
                            print("[prompt.invalid]Use load_images.py in airgap mode to mirror operator images to a private registry and re-run the script")
                            print(Panel.fit(Syntax("python3 load_images.py --airgap", "python")))
                            exit(1)

                    # Display enhanced registry URL format panel
                    print()
                    registry_format_info = Text()
                    registry_format_info.append("🌐 Private Registry URL Format\n\n", style="bold cyan")
                    registry_format_info.append("Supported Formats:\n", style="bold yellow")
                    registry_format_info.append("  • ", style="white")
                    registry_format_info.append("https://", style="green")
                    registry_format_info.append("registry.example.com", style="white")
                    registry_format_info.append(":5000", style="magenta")
                    registry_format_info.append("/path", style="blue")
                    registry_format_info.append("  (HTTPS with custom port and path)\n", style="dim")

                    registry_format_info.append("  • ", style="white")
                    registry_format_info.append("http://", style="green")
                    registry_format_info.append("registry.example.com", style="white")
                    registry_format_info.append(":5000", style="magenta")
                    registry_format_info.append("  (HTTP with custom port)\n", style="dim")

                    registry_format_info.append("  • ", style="white")
                    registry_format_info.append("registry.example.com", style="white")
                    registry_format_info.append(":443", style="magenta")
                    registry_format_info.append("  (HTTPS assumed, custom port)\n", style="dim")

                    registry_format_info.append("  • ", style="white")
                    registry_format_info.append("registry.example.com", style="white")
                    registry_format_info.append("  (HTTPS assumed, port 443)\n\n", style="dim")

                    registry_format_info.append("Examples:\n", style="bold yellow")
                    registry_format_info.append("  • harbor.company.com\n", style="white")
                    registry_format_info.append("  • https://registry.company.com:5000\n", style="white")
                    registry_format_info.append("  • http://localhost:5000\n", style="white")
                    registry_format_info.append("  • quay.io/myorg\n\n", style="white")

                    registry_format_info.append("💡 Tips:\n", style="bold yellow")
                    registry_format_info.append("  • Protocol (http/https) is optional - HTTPS is assumed\n", style="white")
                    registry_format_info.append("  • Port is optional - 443 for HTTPS, 80 for HTTP\n", style="white")
                    registry_format_info.append("  • Path is optional - use for nested registries\n", style="white")
                    registry_format_info.append("  • Use ", style="white")
                    registry_format_info.append("--tls-verify=false", style="cyan")
                    registry_format_info.append(" flag to disable SSL verification\n", style="white")

                    print(Panel(
                        registry_format_info,
                        title="[bold white]Registry URL Configuration[/bold white]",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    print()

                    while True:
                        private_reg_hostname_full = questionary.text(
                            "Enter the private registry URL:",
                            style=Style([
                                ('qmark', 'fg:cyan bold'),
                                ('question', 'bold'),
                                ('answer', 'fg:cyan bold'),
                            ])
                        ).ask()

                        # Handle cancellation
                        private_reg_hostname_full = handle_cancelled_prompt(private_reg_hostname_full, "Private registry URL entry cancelled by user")

                        if private_reg_hostname_full == "":
                            print()
                            print("[prompt.invalid]Private registry hostname can't be empty. Please try again.")
                            continue

                        # Split hostname into scheme, server, context and port using urlparse
                        # Following the syntax specifications in RFC 1808, urlparse recognizes a netloc only if it is properly introduced by '//'.
                        if "://" not in private_reg_hostname_full:
                            private_reg_hostname_full_shema = "//" + private_reg_hostname_full
                        else:
                            private_reg_hostname_full_shema = private_reg_hostname_full

                        private_reg_parts = urlparse(url=private_reg_hostname_full_shema, scheme="https")
                        self._logger.info(f"Private registry URL parts: {private_reg_parts}")
                        if not private_reg_parts.hostname:
                            print()
                            print("[prompt.invalid]Private registry URL must include a hostname. Please try again.")
                            continue

                        self._private_registry_host = private_reg_parts.hostname

                        # If no port is provided, default to 443 for https and 80 for http
                        # Use 443 if no schema is provided
                        private_reg_scheme = private_reg_parts.scheme
                        if private_reg_parts.port is None:
                            if private_reg_parts.scheme == "http":
                                self._private_registry_port = 80
                            else:
                                self._private_registry_port = 443
                        else:
                            self._private_registry_port = private_reg_parts.port

                        # Ask if SSL is to be used for private registry
                        if private_reg_scheme == "https":
                            self._private_registry_ssl_enabled = True
                        else:
                            # Query user if they want to use SSL
                            print()
                            self._private_registry_ssl_enabled = questionary.confirm(
                                "Do you want to use SSL to connect to the private registry?",
                                default=False,
                                style=Style([
                                    ('qmark', 'fg:cyan bold'),
                                    ('question', 'bold'),
                                    ('answer', 'fg:cyan bold'),
                                ])
                            ).ask()

                        # Store registry server WITHOUT protocol for Docker/Skopeo compatibility
                        # Docker registries expect format: hostname:port/path, NOT https://hostname:port/path
                        # Note: Omit standard ports (80 for HTTP, 443 for HTTPS) as Docker/Skopeo don't require them

                        # Build base registry address (hostname or hostname:port)
                        base_registry = self._private_registry_host
                        # Only add port if it's not a standard port
                        if private_reg_scheme == "https" and self._private_registry_port != 443:
                            base_registry = f"{base_registry}:{self._private_registry_port}"
                        elif private_reg_scheme == "http" and self._private_registry_port != 80:
                            base_registry = f"{base_registry}:{self._private_registry_port}"
                        elif private_reg_scheme not in ["http", "https"]:
                            # For other schemes or when scheme is not set, always include port
                            base_registry = f"{base_registry}:{self._private_registry_port}"

                        # Add path if present
                        if private_reg_parts.path != "":
                            self._private_registry_path = private_reg_parts.path.strip('/')
                            self._private_registry_full_server = f"{base_registry}/{self._private_registry_path}"
                        else:
                            self._private_registry_full_server = base_registry

                        self._logger.info(f"Private registry server (for Docker/Skopeo): {self._private_registry_full_server}")

                        print()
                        # Ask if SSL is to be used for private registry
                        # If tls_verify is False we wont ask for the SSL certificate
                        if self._private_registry_ssl_enabled:
                            if not self._tls_verify:
                                print()
                                print(Text("TLS verification is disabled. Podman login will attempt without supplying an SSL certificate", style="yellow"))
                                print()
                            else:
                                self.collect_private_registry_ssl_details()

                        # Test for SSL connections
                        # Return a connection object, RTT and a boolean indicating if the connection was successful
                        if self._private_registry_ssl_enabled and self._tls_verify:
                            conn_result, rtt, connected = connect_to_server(self._private_registry_host, int(self._private_registry_port),
                                                                            True, self._private_registry_ssl_cert, logger=self._logger)
                        else:
                            conn_result, rtt, connected = connect_to_server(self._private_registry_host, int(self._private_registry_port), logger=self._logger)

                        if not connected:
                            print()
                            print(
                                f"[prompt.invalid]Private registry could not be reached. Please check the hostname and port and try again.")
                            continue

                        msg = "Successfully Validated Private Registry Server Reachability"
                        if self._private_registry_ssl_enabled:
                            msg = f"{msg} over SSL"
                        msg_panel = Panel.fit(msg, style="bold green")
                        print()
                        print(msg_panel)
                        break

                    self.verify_private_registry()
                    break
            else:
                if self._private_registry_ssl_enabled:
                    self._logger.info(f"TLS verification is set to {self._tls_verify} for private registry SSL connection")
                    self.collect_private_registry_ssl_details()

                # Use RegistryAuthenticator for both reachability and auth — same path
                # as interactive mode, no dependency on progress objects.
                scheme = "https" if self._private_registry_ssl_enabled else "http"
                registry_url = f"{scheme}://{self._private_registry_host}:{self._private_registry_port}"
                registry_config = RegistryConfig.from_url(
                    url=registry_url,
                    tls_verify=self._tls_verify,
                    ssl_cert_path=Path(self._private_registry_ssl_cert) if self._private_registry_ssl_enabled and self._tls_verify and self._private_registry_ssl_cert else None
                )
                credentials = RegistryCredentials(
                    username=self._private_registry_username,
                    password=self._private_registry_password
                )
                authenticator = RegistryAuthenticator(registry_config, credentials, self._logger)

                # Step 1 — reachability
                reach = authenticator.check_reachability()
                if not reach.reachable:
                    print()
                    print(f"[prompt.invalid]Private registry could not be reached. Please check the hostname and port and try again.")
                    self._logger.error(f"Private registry unreachable: {reach.error}")
                    exit(1)

                msg = "Successfully Validated Private Registry Server Reachability"
                if self._private_registry_ssl_enabled:
                    msg = f"{msg} over SSL"
                print()
                print(Panel.fit(msg, style="bold green"))

                # Step 2 — credentials
                auth_result = authenticator.authenticate_http()
                self._private_registry_valid = auth_result.success
                if not self._private_registry_valid:
                    print()
                    print("[prompt.invalid]Private registry credentials could not be authenticated. Please try again")
                    self._logger.error(f"Private registry auth failed: {auth_result.error}")
                    exit(1)

                self._private_registry = True
                msg = "Successfully Authenticated with Private Registry"
                if self._private_registry_ssl_enabled:
                    msg = f"{msg} over SSL"
                self._logger.info(msg)
                print()
                print(Panel.fit(msg, style="bold green"))

        except Exception as e:
            self._logger.exception(
                f"Exception from gather Class in private registry function -  {str(e)}")

    def collect_private_registry_ssl_details(self):
        self._logger.info("Collecting private registry SSL details")
        if not self._silent_mode:
            # Display SSL certificate options panel
            print()
            ssl_info = Text()
            ssl_info.append("🔒 SSL Certificate Configuration\n\n", style="bold cyan")
            ssl_info.append("Choose how to handle SSL certificates for your private registry:\n\n", style="white")
            ssl_info.append("Options:\n", style="bold yellow")
            ssl_info.append("  1. ", style="white")
            ssl_info.append("Self-Signed Certificate", style="bold white")
            ssl_info.append(" - Provide path to your custom CA certificate\n", style="dim")
            ssl_info.append("  2. ", style="white")
            ssl_info.append("Trusted Certificate", style="bold white")
            ssl_info.append(" - Use system's trusted CA certificates\n", style="dim")
            ssl_info.append("  3. ", style="white")
            ssl_info.append("Skip TLS Verification", style="bold white")
            ssl_info.append(" - Disable certificate validation (not recommended for production)\n\n", style="dim")

            ssl_info.append("💡 Tip: ", style="bold yellow")
            ssl_info.append("Most registries with valid certificates from trusted CAs (Let's Encrypt, DigiCert, etc.) ", style="white")
            ssl_info.append("don't require a custom certificate file.\n", style="white")

            print(Panel(
                ssl_info,
                title="[bold white]SSL Certificate Options[/bold white]",
                border_style="cyan",
                padding=(1, 2)
            ))
            print()

            # Ask user to select SSL certificate option
            ssl_choice = questionary.select(
                "Select SSL certificate handling option:",
                choices=[
                    "Self-Signed Certificate - Provide path to your custom CA certificate",
                    "Trusted Certificate - Use system's trusted CA certificates",
                    "Skip TLS Verification - Disable certificate validation (not recommended for production)"
                ],
                style=Style([
                    ('qmark', 'fg:cyan bold'),
                    ('question', 'bold'),
                    ('selected', 'fg:cyan bold'),
                    ('pointer', 'fg:cyan bold'),
                    ('highlighted', 'fg:cyan bold'),
                ])
            ).ask()

            # Handle cancellation
            if ssl_choice is None:
                print()
                print("[yellow]⚠ Operation cancelled by user[/yellow]")
                exit(0)

            if ssl_choice.startswith("Self-Signed Certificate"):
                # Collect self-signed certificate path
                while True:
                    print()
                    self._private_registry_ssl_cert = questionary.text(
                        "Enter the file path to the private registry SSL certificate:",
                        style=Style([
                            ('qmark', 'fg:cyan bold'),
                            ('question', 'bold'),
                            ('answer', 'fg:cyan bold'),
                        ])
                    ).ask()

                    # Handle cancellation
                    self._private_registry_ssl_cert = handle_cancelled_prompt(self._private_registry_ssl_cert, "SSL certificate path entry cancelled by user")

                    if self._private_registry_ssl_cert == "":
                        print()
                        print("[prompt.invalid]Private registry SSL certificate file path can't be empty. Please try again.")
                        self._logger.debug("Private registry SSL certificate file path can't be empty. Please try again.")
                        continue

                    if not os.path.exists(self._private_registry_ssl_cert):
                        print()
                        print("[prompt.invalid]Private Registry SSL certificate can't be found. Please try again.")
                        self._logger.debug("Private registry SSL certificate can't be found. Please try again.")
                        continue

                    if not check_pem_cert_format(self._private_registry_ssl_cert):
                        print()
                        print("[prompt.invalid]Private registry SSL certificate is not in PEM format. Please try again.")
                        self._logger.debug("Private registry SSL certificate is not in PEM format. Please try again.")
                        continue

                    break
            elif ssl_choice.startswith("Skip TLS Verification"):
                # Disable TLS verification
                self._tls_verify = False
                self._private_registry_ssl_cert = None
                print()
                print(Text("⚠ TLS verification disabled. Connection will not validate SSL certificates.", style="yellow"))
                self._logger.info("TLS verification disabled by user choice")
            else:
                # Use system certificates (Trusted Certificate option)
                self._private_registry_ssl_cert = None
                print()
                print(Text("✓ Using system's trusted CA certificates for SSL verification.", style="green"))
                self._logger.info("Using system CA certificates for TLS verification")
        else:
            # Silent mode - validate certificate if provided
            if self._private_registry_ssl_cert:
                if not os.path.exists(self._private_registry_ssl_cert):
                    print()
                    print("[prompt.invalid]Private Registry SSL certificate can't be found. Please try again.")
                    self._logger.debug("Private Registry SSL certificate can't be found. Please try again.")
                    exit(1)

                if not check_pem_cert_format(self._private_registry_ssl_cert):
                    print()
                    print("[prompt.invalid]Private registry SSL certificate is not in PEM format. Please try again.")
                    self._logger.debug("Private registry SSL certificate is not in PEM format. Please try again.")
                    exit(1)
            else:
                self._logger.info("No SSL certificate provided in silent mode - using system CA certificates")

    # Function to check if private catalog is being used
    def collect_private_catalog(self):
        self._logger.info("Collecting catalog information")
        if self._platform != "other":
            print()
            print(Panel.fit("Private Catalog"))
            print()
            print("The IBM Content Assistant Operator Catalog Source can be installed with the follow options:\n"
                  "1. Private Catalog - Install the catalog in the same target namespace\n"
                  "2. Global Catalog - Install the catalog in the openshift-marketplace namespace")
            print()
            print("A private catalog can only be used by operator instances in the same namespace.\n"
                  "A global catalog can be used by operator instances in any namespace.")
            print()
            print("Note: Private catalog is the default and recommended option.")
            self._private_catalog = not (Confirm.ask(
                "Do you want to deploy IBM Content Assistant Operator using a global catalog?", default=False))
            
            if self._private_catalog:
                self._logger.info("Selected Private catalogue")
            else:
                self._logger.info("Selected global catalogue")

    # Display preupgrade steps to be done
    # TBD for Jason to add more content to display
    def display_preupgrade_steps(self):
        print(Panel.fit("Pre Upgrade Checklist"))
        print()
        upgrade_link = Text(
            "https://www.ibm.com/docs/SSNW2F_5.7.0/com.ibm.p8.containers.doc/containers_upgrading_licenseV559.htm",
            style="link https://www.ibm.com/docs/SSNW2F_5.7.0/com.ibm.p8.containers.doc/containers_upgrading_licenseV559.htm")
        while True:
            print(
                f"Please see IBM Content Assistant Documentation for important upgrade prerequisites: {upgrade_link}")
            self._preupgrade_steps = Confirm.ask(
                "Have you completed IBM Content Assistant Operator upgrade prerequisites")
            if not self._preupgrade_steps:
                print("Please complete upgrade prerequisites before continuing")
                exit(1)
            else:
                break

    # Create a function to print all the deployment options
    def print_deployment_options(self):
        self._logger.info("namespace-", self._namespace)
        self._logger.info("platform-", self._platform)
        self._logger.info("podman present-", self._podman_available)
        self._logger.info("oc logged in", self._ocp_logged_in)
        return_dict = {}
        if self._script_type.lower() == "cleanup":
            return_dict = {
                "namespace": self._namespace,
                "platform": self._platform,
                "podman present": self._podman_available,
                "Cluster connection": self._ocp_logged_in
            }
        print(return_dict)
