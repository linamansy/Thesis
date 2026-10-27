# Study 2 law corpus: article selection rule

Written 27 Oct 2026, before any passage is built, any retrieval is run or any silver label is made for this corpus.
This step only selects articles. It replaces neither the GDPR-only corpus nor any frozen retrieval or silver file.

## 1. Laws and sources

All five laws form ONE corpus that is searched for every case.

| prefix | law | text used | version / consolidation date | source (CELLAR, behind EUR-Lex) | downloaded | file | SHA-256 |
|---|---|---|---|---|---|---|---|
| GDPR | Regulation (EU) 2016/679 | original OJ text (OJ L 119, 4.5.2016) | 4.5.2016 (no amending acts) | https://publications.europa.eu/resource/celex/32016R0679 | 2026-10-24 | data/knowledge_gdpr/raw/GDPR_2016_679.html | 962539af03738bf552319ff4ce42d69e5f95a576307c4dfed7bf87e81b646b9d |
| CRD | Directive 2011/83/EU | consolidated text 02011L0083-20220528 (incl. Directive (EU) 2015/2302 and (EU) 2019/2161) | 28.5.2022 | https://publications.europa.eu/resource/celex/02011L0083-20220528 | 2026-10-27 | data/knowledge_study2_corpus/raw/CRD_2011_83_consolidated_20220528.html | 23b2e4199b115ac65876ec315cdf623abea24db69580f41e32b651e155540cfe |
| LPD | Directive 2011/7/EU | original OJ text (OJ L 48, 23.2.2011) | 23.2.2011 | https://publications.europa.eu/resource/celex/32011L0007 | 2026-10-14 | data/knowledge/raw/LPD_2011_7.html | 629ef52ec778231f930dc82d7c5a0698bb6f6385b1d051e741451541cb03be01 |
| SGD | Directive (EU) 2019/771 | original OJ text (OJ L 136, 22.5.2019) | 22.5.2019 | https://publications.europa.eu/resource/celex/32019L0771 | 2026-10-27 | data/knowledge_study2_corpus/raw/SGD_2019_771.html | b40ba573f6a1800cf766c0a89fd894e99c45a2ff7e1418ff76a77a1b3e9632d6 |
| ECD | Directive 2000/31/EC | original OJ text (OJ L 178, 17.7.2000), legacy HTML | 17.7.2000 | https://publications.europa.eu/resource/celex/32000L0031 | 2026-10-24 | data/knowledge_study2/raw/ECD_2000_31.html | ace6f4c0e50a12845be213ad6094ce38f06a5dd2784fdf07b91b7d2e19f0eaaf |

Download method: curl with `Accept: application/xhtml+xml` and `Accept-Language: eng` (ECD: `Accept: text/html`,
no XHTML exists), as for the earlier corpora. GDPR, LPD and ECD reuse the files already in the repository.

## 2. Rule (same for all five laws)

**Keep** an operative article if it puts a duty on a business: a trader, seller, service provider, controller,
processor, or a creditor/debtor undertaking. A duty is something the business must do, must not do, or must honour
(a right of the consumer, buyer or data subject that the business has to grant). An article written as "Member
States shall ensure that the trader ..." is judged by its substance: if the business is the one that must act, it
is kept.

**Exclude**:
- definitions;
- subject matter, objectives and scope (incl. level of harmonisation);
- duties of Member States, the Commission, supervisory authorities or the Board;
- penalties and fines;
- transposition;
- reports and review;
- entry into force, addressees, repeals, amendments of other acts and other final provisions.

Articles that put no duty on a business are excluded too: duties only on the consumer or another person, pure legal
effects that need no action by the business, exceptions or exemptions that remove a duty, and rules for court
disputes (remedies against authorities, liability for damages, burden of proof).

The rule keeps or excludes whole articles.

**Unit**: one passage per article paragraph, lettered points kept with their paragraph, as in the GDPR corpus
(DirectiveChunker). Passages are built only after this selection is approved.
