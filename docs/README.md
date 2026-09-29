# IBM Content Assistant — GitHub Pages Site

This directory contains the GitHub Pages site for the **IBM Content Assistant** client-managed software repository.

## 🌐 Live Sites

| Environment | URL |
|---|---|
| **Public (Production)** | `https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software` |
| **Internal Dev (GHE Pages)** | `https://pages.github.ibm.com/dba/cert-kubernetes-content-assistant` |

Helm chart repository URL (for `helm repo add`):
```
https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/charts
```

## 📁 Structure

```
docs/
├── index.html              # Home page — hero, features, architecture overview, quick start
├── helm-charts.html        # Helm charts repository page
├── releases.html           # Releases and patches page
├── README.md               # This file
├── helm-charts/            # Helm chart .tgz artifacts
│   ├── ibm-content-assistant-1.4.0.tgz   # IBM Content Assistant Operator chart
│   └── ibm-usage-metering-1.0.7.tgz      # IBM Usage Metering Service chart
└── assets/
    ├── ICALogo.svg         # IBM Content Assistant logo
    ├── favicon.svg         # Favicon (ICALogo.svg content)
    ├── WDU.svg             # IBM Usage Metering Service icon
    ├── ContentCortex.svg   # IBM Content Cortex icon
    ├── AIModelGateway.svg  # AI model gateway icon
    ├── CNPG.svg            # Cloud Native PG icon
    ├── red-hat-1.svg       # Red Hat icon (used in releases page)
    ├── redis.svg           # Redis icon
    ├── styles.css          # Main stylesheet (IBM Carbon design tokens)
    ├── script.js           # Environment detection, URL rewriting, shared JS
    ├── helm-charts.css     # Helm charts page styles
    ├── helm-charts.js      # Helm charts page tab/version selector scripts
    ├── releases.css        # Releases page styles
    └── releases.js         # Releases page scripts
```

## 🎨 Design System

The site uses the **IBM Carbon Design System v11**:

- **Component library**: `@carbon/web-components` and `@carbon/styles` (CDN)
- **Typography**: IBM Plex Sans, IBM Plex Mono
- **Colors**: IBM Carbon color palette (Blue 60, Gray scale, semantic tokens)
- **Components**: Carbon tiles, buttons, tags, navigation, tabs, code snippets

## 🏗️ Architecture

IBM Content Assistant is a **single-chart add-on** to IBM Content Cortex or CP4BA:

| Component | How deployed |
|---|---|
| **IBM Content Assistant Operator** | Installed via Helm chart (`ibm-content-assistant-1.4.0.tgz`) |
| **GenAI Connector Service** | Deployed and managed automatically by the operator |
| **IBM Usage Metering Service (UMS)** | Separate Helm chart (`ibm-usage-metering-1.0.7.tgz`) |
| **CPE + Content Navigator** | Prerequisite — existing IBM Content Cortex or CP4BA deployment |
| **IBM watsonx LLM / AI Model Gateway** | External — IBM Cloud, AWS, self-managed, or via IBM AI Model Gateway proxy |

## 📄 Pages

### Home Page (`index.html`)
- Hero section with product overview
- Key features grid
- Quick start guide (Python script, 3-step flow)
- Architecture overview (operator, GenAI Connector, foundation prereqs, UMS, watsonx)
- Resource links

### Helm Charts Page (`helm-charts.html`)
- Helm repository info and `helm repo add` quick command
- Environment-aware URLs (public vs. internal GHE, controlled by `script.js`)
- **IBM Content Assistant Operator** chart card (v1.0.4) — features + configuration values tabs
- **IBM Usage Metering Service** chart card (v1.0.7) — features tab
- Complete installation guide with three method tabs:
  - **Python Script** (recommended) — guided interactive deployment
  - **OpenShift Integration** — `HelmChartRepository` / `ProjectHelmChartRepository` CRs
  - **Helm CLI** — manual `helm repo add` + `helm install` steps

### Releases & Patches Page (`releases.html`)
- Release stream selector (currently: **1.0.x** only)
- **1.0.4** release card — component versions, base image versions, system requirements, resource links
- Patch history section
- Upgrade guide — supported upgrade path (`any 1.0.x → 1.0.4`), Helm upgrade command

## 🔧 Environment Detection

[`assets/script.js`](assets/script.js) auto-detects whether the page is served from the public GitHub Pages host or the internal IBM GHE Pages host, and rewrites URLs accordingly at runtime.

**`window.SITE_ENV` tokens:**

| Token | Public value | Internal (dev) value |
|---|---|---|
| `pagesBase` | `https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software` | `https://pages.github.ibm.com/dba/cert-kubernetes-content-assistant` |
| `chartsBase` | `https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/charts` | `https://pages.github.ibm.com/dba/cert-kubernetes-content-assistant` |
| `repoBase` | `https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software` | `https://github.ibm.com/dba/cert-kubernetes-content-assistant` |
| `repoName` | `ibm-content-assistant-client-managed-software` | `cert-kubernetes-content-assistant` |

**HTML element attributes processed by `script.js`:**

| Attribute | Effect |
|---|---|
| `data-href-env="pagesBase/helm-charts/ibm-content-assistant-1.4.0.tgz"` | Sets `href` to the resolved URL |
| `data-text-env="chartsBase"` | Sets `textContent` to the resolved value |
| `data-cmd="helm repo add ibm-content-assistant {chartsBase}"` | Rewrites `<code>` child text in a `<pre>` block |
| `data-public-only` | Hidden on internal dev environment |
| `data-internal-only` | Hidden on public environment |

## 🔧 Maintenance

### Adding a New Patch Release

1. Edit [`releases.html`](releases.html)
2. Add a new `release-card` block for the new version above the existing one
3. Update component versions, base image versions, and resource links
4. Add a new `ifix-card` entry to the patch history section
5. Update the upgrade path in the Upgrade Guide section

### Updating Helm Charts

1. Add the new chart `.tgz` file to `docs/helm-charts/`
2. Update [`helm-charts.html`](helm-charts.html):
   - Update `chart-version`, `data-version`, and `meta-value` fields
   - Update the `data-href-env` download link to the new filename
   - Update configuration values in the Values tab
3. Regenerate the Helm repository index:
   ```bash
   helm repo index docs/helm-charts \
     --url https://ibm-ecm.github.io/ibm-content-assistant-client-managed-software/helm-charts
   ```

### Updating the Favicon / Logo

Replace [`assets/favicon.svg`](assets/favicon.svg) with new SVG content.
The `ICALogo.svg` source is kept separately at [`assets/ICALogo.svg`](assets/ICALogo.svg).

## 🚀 Deployment

The site is automatically deployed via GitHub Pages when changes are pushed to the `gh-pages` branch.

### GitHub Pages Settings
- **Source**: `gh-pages` branch, `/docs` folder
- **HTTPS**: Enabled

## 📦 External Dependencies (CDN)

| Dependency | Used for |
|---|---|
| `@carbon/styles@latest` | Carbon Design System CSS |
| `@carbon/web-components@latest` | Carbon Web Components |
| `IBM Plex Sans` (Google Fonts) | Body typography |
| `IBM Plex Mono` (Google Fonts) | Code typography |

## 🧪 Browser Support

- Chrome / Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome for Android)

## 📞 Support

- Open an issue: [GitHub Issues](https://github.com/ibm-ecm/ibm-content-assistant-client-managed-software/issues)
- Contact: ecm-container-service@ibm.com
- IBM Support: https://www.ibm.com/mysupport

## 📄 License

Licensed Materials - Property of IBM

© Copyright IBM Corp. 2026. All Rights Reserved.

US Government Users Restricted Rights - Use, duplication or disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
