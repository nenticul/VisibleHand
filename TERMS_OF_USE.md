# VisibleHand API Terms of Use

**Effective date:** 2026-06-27  
**Version:** 1.0

---

## 1. The API is Free

The VisibleHand API and its scores are provided free of charge under the MIT License.
There is no fee for access, no rate limits beyond fair-use limits, and no registration
required for public endpoints.

---

## 2. What You Can Do

- Query the API for any purpose, including research, education, journalism, and
  personal projects.
- Display scores and visualisations in reports, dashboards, and publications.
- Build applications that consume the API, including commercial applications,
  subject to Section 3.
- Cite VisibleHand scores in academic papers (please cite the methodology document).

---

## 3. Upstream Data Restrictions (Important for Commercial Users)

VisibleHand's scores are derived from multiple upstream data sources. Some of
these sources restrict commercial use. By using the VisibleHand API, you agree
that **if you use the scores in a commercial product or service, you are
responsible for complying with the upstream data license terms**, including:

| Source | Restriction | Action Required |
|--------|-------------|-----------------|
| **ACLED** | Non-commercial only | Obtain commercial license from ACLED before commercial use |
| **GTD (Global Terrorism Database)** | Non-commercial only | Do not use in commercial products without START permission |
| **REIGN** | Non-commercial only | Contact OEF Research for commercial licensing |
| **IMF data** | Redistribution restricted | Do not redistribute raw IMF data; scores derived from it are acceptable |
| **BIS Statistics** | Non-commercial only | Contact BIS for commercial licensing |

VisibleHand is not a data reseller. It processes these inputs into derived scores.
The legal exposure for upstream license violations rests with the end user, not
with VisibleHand, provided the end user has been notified of these restrictions —
which is the purpose of this document.

For purely academic, research, journalistic, or personal use, no action is required
beyond normal academic attribution.

---

## 4. Attribution

When publishing results based on VisibleHand scores, attribution is appreciated:

> *Country risk scores provided by VisibleHand (api.visiblehand.dev), an open-source
> political-economic risk scoring system.*

For academic publications, please cite the methodology document when available.

---

## 5. No Warranty

VisibleHand scores are provided "as is" without warranty of any kind. They are
analytical tools based on public data and automated scoring — not investment advice,
legal advice, or professional risk assessments. Do not rely on them as the sole
basis for financial, legal, or security decisions.

---

## 6. Prohibited Uses

- Do not use VisibleHand scores to discriminate against individuals based on their
  country of origin in contexts prohibited by applicable law.
- Do not represent VisibleHand scores as your own proprietary data or methodology.
- Do not attempt to reverse-engineer or reproduce the underlying data sources in
  ways that violate the upstream licenses listed in [DATA_SOURCES.md](DATA_SOURCES.md).

---

## 7. Contact

For licensing questions or commercial use inquiries: open an issue at the
[GitHub repository](https://github.com/YOUR_USERNAME/visiblehand) or contact
the maintainer at the address listed in the repository.

---

*These terms apply to use of the public VisibleHand API. For self-hosted deployments,
the MIT License governs. The MIT License is permissive but does not override the
upstream data source restrictions described in Section 3.*
