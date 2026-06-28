# VisibleHand Data Sources

Every source used by VisibleHand is documented here with its license, restrictions,
and the specific indicators we extract. This document is kept current with the
codebase; if a source is added or removed, this file is updated in the same commit.

---

## Economic Data

| Source | License | Restrictions | Indicators | Update Frequency |
|--------|---------|--------------|------------|-----------------|
| **World Bank WDI** | [CC BY 4.0](https://datacatalog.worldbank.org/public-licenses) | Commercial use permitted | GDP growth, inflation, debt/GDP, FX reserves, current account, unemployment, tax revenue, remittances | Annual (data) / Quarterly (releases) |
| **IMF World Economic Outlook (WEO)** | [IMF terms](https://www.imf.org/external/terms.htm) | Free for research and non-commercial use; commercial redistribution restricted | GDP projections, inflation projections, debt projections | Biannual (April, October) |
| **IMF International Financial Statistics (IFS)** | IMF terms | Same as WEO | Exchange rates, monetary aggregates, reserves | Monthly |
| **IMF Financial Soundness Indicators (FSI)** | IMF terms | Same as WEO | Bank NPL ratios, capital adequacy | Quarterly |
| **BIS Statistics** | [BIS terms](https://www.bis.org/terms_conditions.htm) | Free for non-commercial use; credit required | Credit-to-GDP gap, total credit, bank capital | Quarterly |
| **FRED (Federal Reserve)** | Public domain | No restrictions | DXY, commodity indices, US yields | Daily |
| **DBnomics** | Aggregator of public statistics | Varies by underlying source | Multiple macroeconomic series | Varies |
| **ILO ILOSTAT** | [CC BY 4.0](https://ilostat.ilo.org/resources/ilostat-terms-use/) | Commercial use permitted | Unemployment, labour force participation | Annual |
| **Frankfurter API** | Public domain / open source | No restrictions | Daily FX rates | Daily |

---

## Political & Governance Data

| Source | License | Restrictions | Coverage | Update Frequency |
|--------|---------|--------------|----------|-----------------|
| **GDELT 2.0** | Public domain | No restrictions | 250+ countries | 15 minutes |
| **ACLED** | [ACLED terms](https://acleddata.com/acleddatanerd/terms-of-use/) | **Free for academic and non-commercial use only.** Commercial use requires a separate license from ACLED. | ~100 countries | Weekly |
| **V-Dem v14+** | [CC BY 4.0](https://www.v-dem.net/data/) | Commercial use permitted with attribution | 180+ countries, 1789–present | Annual |
| **UCDP GED** | [UCDP terms](https://ucdp.uu.se/encyclopedia/faq.html) | Free for academic and non-commercial use | Global | Annual / Quarterly candidates |
| **REIGN** | [OEF terms](http://oefresearch.org/) | Free for non-commercial use | 200+ countries | Monthly |
| **Polity5** | Free for academic use | Non-commercial only | 200+ countries | Annual |
| **Global Terrorism Database (GTD)** | Free for non-commercial research | **Non-commercial only.** Do not use in commercial products without permission from START. | Global | Annual |
| **Freedom House** | [FH terms](https://freedomhouse.org/about-us/content-permissions) | Free for non-commercial use with attribution | 195 countries | Annual |
| **Transparency International CPI** | [CC BY-ND 4.0](https://www.transparency.org/en/cpi) | Attribution required; no derivatives | 180 countries | Annual |
| **WJP Rule of Law Index** | [WJP terms](https://worldjusticeproject.org/our-work/research-and-data) | Free for non-commercial use | 140+ countries | Annual |
| **RSF Press Freedom Index** | [RSF terms](https://rsf.org/en) | Free for non-commercial use | 180 countries | Annual |
| **SIPRI Military Expenditure** | [SIPRI terms](https://www.sipri.org/about/terms-and-conditions) | Free for non-commercial use | 170+ countries | Annual |
| **OFAC Sanctions (US)** | Public domain | No restrictions | All OFAC designations | Ongoing |
| **EU Sanctions** | Public domain | No restrictions | EU designations | Ongoing |
| **UN Security Council Sanctions** | Public domain | No restrictions | UN designations | Ongoing |

---

## NLP / Document Sources

| Source | License | Restrictions | Content |
|--------|---------|--------------|---------|
| **IMF Article IV Staff Reports** | Public domain | No restrictions (publicly available) | Annual country assessments, risk matrices, staff appraisals |
| **IMF Press Releases** | Public domain | No restrictions | Post-consultation statements |
| **World Bank CPF/PLR** | [WB terms](https://www.worldbank.org/en/about/legal) | Free for non-commercial use | Country Partnership Frameworks |
| **Central bank statements** | Public domain (published by central banks) | No restrictions | Policy rate decisions, monetary policy statements |
| **Rating agency public reports** | Public for listed PDFs | Do not redistribute; link only | S&P, Moody's, Fitch public outlook PDFs |
| **GDELT GKG** | Public domain | No restrictions | Pre-computed tone on 100M+ news articles |

---

## Derived / Computed

| Component | Inputs | License |
|-----------|--------|---------|
| Composite risk score | All above | MIT (VisibleHand license) |
| Hawkes process parameters | GDELT / ACLED events | MIT |
| NLP aspect scores | Central bank statements | MIT |
| Governance sub-score | V-Dem, WJP, TI, FH | MIT (with upstream attribution) |

---

## Non-Commercial Source Summary

The following sources restrict commercial use. VisibleHand's API Terms of Use
(see [TERMS_OF_USE.md](TERMS_OF_USE.md)) pass these restrictions to API consumers.
End users who use VisibleHand scores in commercial products are responsible for
obtaining their own licenses from these data providers:

- **ACLED** — commercial license required
- **V-Dem** — attribution required (CC BY 4.0 permits commercial use with attribution)
- **GTD (Global Terrorism Database)** — non-commercial only
- **REIGN / OEF** — non-commercial only
- **IMF data** — redistribution in commercial products restricted
- **BIS Statistics** — non-commercial use only

---

## Updating This File

Any PR that adds or removes a data source must update this file. Run
`grep -r "source=" core/ingestion/ | grep -v ".pyc"` to verify the sources
listed here match what is actually used in the ingestion layer.
