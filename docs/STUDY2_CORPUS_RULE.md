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

> Correction 27 Oct before building: rule first limited to business duties; consumer duties (e.g. CRD Art. 14 returning goods) are process steps, so the rule was widened.

**Keep** an operative article if it puts a duty on ANY party taking part in the process: trader, seller, service
provider, consumer, buyer, recipient, debtor, creditor, controller or processor. A duty is something the party must
do, must not do, or must honour (a right of another party that it has to grant). An article written as "Member
States shall ensure that the trader ..." is judged by its substance: if a process party is the one that must act, it
is kept.

**Exclude** only:
- definitions;
- subject matter, objectives and scope (incl. level of harmonisation);
- duties of Member States, the Commission or authorities (supervisory authorities, the Board);
- penalties and fines;
- transposition;
- reports and review;
- entry into force, addressees, repeals, amendments of other acts and other final provisions.

An article that puts no duty on any process party fails the keep test and is therefore not kept either: pure legal
effects that need no action by anyone, exceptions or exemptions that remove a duty, and rules for court disputes
(remedies, liability for damages, burden of proof).

The rule keeps or excludes whole articles.

**Unit**: one passage per article paragraph, lettered points kept with their paragraph, as in the GDPR corpus
(DirectiveChunker). Passages are built only after this selection is approved.

## 3. Application of the rule (27 Oct 2026, re-applied after the correction)

Article numbers and titles are read from the raw files of section 1 (ECD: from the legacy HTML, as listed in data/knowledge_study2/article_selection.json).

| law | articles | kept | excluded |
|---|---|---|---|
| GDPR | 99 | 37 | 62 |
| CRD | 36 | 14 | 22 |
| LPD | 15 | 3 | 12 |
| SGD | 27 | 12 | 15 |
| ECD | 24 | 5 | 19 |
| total | 201 | 71 | 130 |

### GDPR (EU) 2016/679

| article | title | decision | reason |
|---|---|---|---|
| 1 | Subject-matter and objectives | exclude | subject matter / scope |
| 2 | Material scope | exclude | subject matter / scope |
| 3 | Territorial scope | exclude | subject matter / scope |
| 4 | Definitions | exclude | definitions |
| 5 | Principles relating to processing of personal data | keep | controller must comply with the processing principles and demonstrate it (5(2)) |
| 6 | Lawfulness of processing | keep | controller may process only on a lawful basis |
| 7 | Conditions for consent | keep | controller must demonstrate consent and meet its conditions |
| 8 | Conditions applicable to child's consent in relation to information society services | keep | controller must obtain and verify parental consent for children |
| 9 | Processing of special categories of personal data | keep | prohibition on processing special categories, with conditions |
| 10 | Processing of personal data relating to criminal convictions and offences | keep | conditions on processing criminal-conviction data |
| 11 | Processing which does not require identification | keep | controller must inform the data subject when it cannot identify them (11(2)) |
| 12 | Transparent information, communication and modalities for the exercise of the rights of the data subject | keep | controller must give information and act on requests within set time limits |
| 13 | Information to be provided where personal data are collected from the data subject | keep | controller must give information when collecting data |
| 14 | Information to be provided where personal data have not been obtained from the data subject | keep | controller must give information when data are not collected from the data subject |
| 15 | Right of access by the data subject | keep | data-subject right (access) the controller must honour |
| 16 | Right to rectification | keep | data-subject right (rectification) the controller must honour |
| 17 | Right to erasure (‘right to be forgotten’) | keep | data-subject right (erasure) the controller must honour |
| 18 | Right to restriction of processing | keep | data-subject right (restriction) the controller must honour |
| 19 | Notification obligation regarding rectification or erasure of personal data or restriction of processing | keep | controller must notify recipients of rectification, erasure or restriction |
| 20 | Right to data portability | keep | data-subject right (portability) the controller must honour |
| 21 | Right to object | keep | data-subject right (objection) the controller must honour |
| 22 | Automated individual decision-making, including profiling | keep | controller must not decide solely by automated processing; safeguards |
| 23 | Restrictions | exclude | Union or Member-State law may restrict rights; no duty on any process party |
| 24 | Responsibility of the controller | keep | controller must implement measures and demonstrate compliance |
| 25 | Data protection by design and by default | keep | controller must apply data protection by design and by default |
| 26 | Joint controllers | keep | joint controllers must set out their responsibilities |
| 27 | Representatives of controllers or processors not established in the Union | keep | controller/processor outside the EU must designate a representative |
| 28 | Processor | keep | controller must use compliant processors under a contract; processor duties |
| 29 | Processing under the authority of the controller or processor | keep | processor and staff process only on the controller's instructions |
| 30 | Records of processing activities | keep | controller and processor must keep records of processing |
| 31 | Cooperation with the supervisory authority | keep | controller and processor must cooperate with the supervisory authority |
| 32 | Security of processing | keep | controller and processor must ensure security of processing |
| 33 | Notification of a personal data breach to the supervisory authority | keep | controller must notify a data breach to the supervisory authority |
| 34 | Communication of a personal data breach to the data subject | keep | controller must communicate a data breach to the data subject |
| 35 | Data protection impact assessment | keep | controller must carry out a data protection impact assessment |
| 36 | Prior consultation | keep | controller must consult the supervisory authority before high-risk processing |
| 37 | Designation of the data protection officer | keep | controller and processor must designate a data protection officer |
| 38 | Position of the data protection officer | keep | controller and processor must involve and support the data protection officer |
| 39 | Tasks of the data protection officer | keep | data protection officer (a process party within the controller/processor) must perform the listed tasks |
| 40 | Codes of conduct | exclude | Member States, authorities, Board and Commission encourage and approve codes of conduct |
| 41 | Monitoring of approved codes of conduct | exclude | duty on monitoring bodies and supervisory authorities |
| 42 | Certification | exclude | voluntary certification; duties on Member States, authorities, Board and Commission |
| 43 | Certification bodies | exclude | duty on certification bodies and Member States |
| 44 | General principle for transfers | keep | controller and processor may transfer data abroad only under Chapter V conditions |
| 45 | Transfers on the basis of an adequacy decision | exclude | duty on the Commission (adequacy decisions); para 1 permits transfers, sets no duty |
| 46 | Transfers subject to appropriate safeguards | keep | controller/processor may transfer only with appropriate safeguards |
| 47 | Binding corporate rules | exclude | duty on supervisory authorities (approval of binding corporate rules) |
| 48 | Transfers or disclosures not authorised by Union law | exclude | recognition of third-country court or authority decisions; no duty on any process party |
| 49 | Derogations for specific situations | keep | conditions for derogation transfers; controller must inform and document |
| 50 | International cooperation for the protection of personal data | exclude | duty on the Commission and supervisory authorities (international cooperation) |
| 51 | Supervisory authority | exclude | duty on the Member States (setting up supervisory authorities) |
| 52 | Independence | exclude | duty on supervisory authorities |
| 53 | General conditions for the members of the supervisory authority | exclude | duty on the Member States (setting up supervisory authorities) |
| 54 | Rules on the establishment of the supervisory authority | exclude | duty on the Member States (setting up supervisory authorities) |
| 55 | Competence | exclude | duty on supervisory authorities |
| 56 | Competence of the lead supervisory authority | exclude | duty on supervisory authorities |
| 57 | Tasks | exclude | duty on supervisory authorities |
| 58 | Powers | exclude | duty on supervisory authorities |
| 59 | Activity reports | exclude | duty on supervisory authorities |
| 60 | Cooperation between the lead supervisory authority and the other supervisory authorities concerned | exclude | duty on supervisory authorities |
| 61 | Mutual assistance | exclude | duty on supervisory authorities |
| 62 | Joint operations of supervisory authorities | exclude | duty on supervisory authorities |
| 63 | Consistency mechanism | exclude | duty on supervisory authorities and the Board (consistency mechanism) |
| 64 | Opinion of the Board | exclude | duty on supervisory authorities and the Board (consistency mechanism) |
| 65 | Dispute resolution by the Board | exclude | duty on supervisory authorities and the Board (consistency mechanism) |
| 66 | Urgency procedure | exclude | duty on supervisory authorities and the Board (consistency mechanism) |
| 67 | Exchange of information | exclude | duty on supervisory authorities and the Board (consistency mechanism) |
| 68 | European Data Protection Board | exclude | duty on the Board |
| 69 | Independence | exclude | duty on the Board |
| 70 | Tasks of the Board | exclude | duty on the Board |
| 71 | Reports | exclude | duty on the Board |
| 72 | Procedure | exclude | duty on the Board |
| 73 | Chair | exclude | duty on the Board |
| 74 | Tasks of the Chair | exclude | duty on the Board |
| 75 | Secretariat | exclude | duty on the Board |
| 76 | Confidentiality | exclude | duty on the Board |
| 77 | Right to lodge a complaint with a supervisory authority | exclude | remedy against a supervisory authority |
| 78 | Right to an effective judicial remedy against a supervisory authority | exclude | remedy against a supervisory authority |
| 79 | Right to an effective judicial remedy against a controller or processor | exclude | court remedy against a controller or processor (court disputes) |
| 80 | Representation of data subjects | exclude | representation of data subjects in complaints and court actions |
| 81 | Suspension of proceedings | exclude | suspension of court proceedings |
| 82 | Right to compensation and liability | exclude | liability for damages (court disputes) |
| 83 | General conditions for imposing administrative fines | exclude | penalties (administrative fines) |
| 84 | Penalties | exclude | penalties |
| 85 | Processing and freedom of expression and information | exclude | duty on the Member States (specific processing situations) |
| 86 | Processing and public access to official documents | exclude | duty on the Member States (specific processing situations) |
| 87 | Processing of the national identification number | exclude | duty on the Member States (specific processing situations) |
| 88 | Processing in the context of employment | exclude | duty on the Member States (specific processing situations) |
| 89 | Safeguards and derogations relating to processing for archiving purposes in the public interest, scientific or historical research purposes or statistical purposes | exclude | safeguards and derogations set by Union or Member-State law |
| 90 | Obligations of secrecy | exclude | duty on the Member States (specific processing situations) |
| 91 | Existing data protection rules of churches and religious associations | exclude | duty on the Member States (specific processing situations) |
| 92 | Exercise of the delegation | exclude | duty on the Commission (delegated acts) |
| 93 | Committee procedure | exclude | duty on the Commission (committee procedure) |
| 94 | Repeal of Directive 95/46/EC | exclude | final provisions (repeal) |
| 95 | Relationship with Directive 2002/58/EC | exclude | final provisions (relationship with other acts) |
| 96 | Relationship with previously concluded Agreements | exclude | final provisions (relationship with agreements) |
| 97 | Commission reports | exclude | reports / review |
| 98 | Review of other Union legal acts on data protection | exclude | reports / review |
| 99 | Entry into force and application | exclude | final provisions (entry into force) |

### Consumer Rights Directive 2011/83/EU (consolidated 28.5.2022)

| article | title | decision | reason |
|---|---|---|---|
| 1 | Subject matter | exclude | subject matter / scope |
| 2 | Definitions | exclude | definitions |
| 3 | Scope | exclude | subject matter / scope |
| 4 | Level of harmonisation | exclude | subject matter / scope (level of harmonisation) |
| 5 | Information requirements for contracts other than distance or off-premises contracts | keep | trader must give information before on-premises contracts |
| 6 | Information requirements for distance and off-premises contracts | keep | trader must give information before distance and off-premises contracts |
| 6a | Additional specific information requirements for contracts concluded on online marketplaces | keep | online marketplace provider must give additional information |
| 7 | Formal requirements for off-premises contracts | keep | trader must meet formal requirements for off-premises contracts |
| 8 | Formal requirements for distance contracts | keep | trader must meet formal requirements for distance contracts |
| 9 | Right of withdrawal | keep | consumer right of withdrawal the trader must honour |
| 10 | Omission of information on the right of withdrawal | keep | withdrawal period the trader must honour is extended if information is omitted |
| 11 | Exercise of the right of withdrawal | keep | trader must accept the withdrawal and acknowledge online withdrawals |
| 12 | Effects of withdrawal | exclude | legal effect of withdrawal (ends both parties' obligations); no action by the trader |
| 13 | Obligations of the trader in the event of withdrawal | keep | trader must reimburse payments after withdrawal |
| 14 | Obligations of the consumer in the event of withdrawal | keep | consumer must return the goods within 14 days and bears the stated costs |
| 15 | Effects of the exercise of the right of withdrawal on ancillary contracts | exclude | legal effect (ancillary contracts end automatically); duty on the Member States |
| 16 | Exceptions from the right of withdrawal | exclude | exceptions that remove the right of withdrawal; no duty |
| 17 | Scope | exclude | subject matter / scope |
| 18 | Delivery | keep | trader must deliver the goods on time |
| 19 | Fees for the use of means of payment | keep | trader must not charge fees above its cost for means of payment |
| 20 | Passing of risk | exclude | legal effect (passing of risk); no action by the trader |
| 21 | Communication by telephone | keep | trader's telephone line must not cost the consumer more than the basic rate |
| 22 | Additional payments | keep | trader must get express consent for additional payments |
| 23 | Enforcement | exclude | duty on the Member States (enforcement) |
| 24 | Penalties | exclude | penalties |
| 25 | Imperative nature of the Directive | exclude | legal effect (waiving terms are not binding); duty on the Member States |
| 26 | Information | exclude | duty on the Member States (informing consumers) |
| 27 | Inertia selling | exclude | legal effect (consumer exempt from paying for unsolicited supply); no action by the trader |
| 28 | Transposition | exclude | transposition |
| 29 | Reporting requirements | exclude | duty on the Member States (reporting) |
| 30 | Reporting by the Commission and review | exclude | reports / review |
| 31 | Repeals | exclude | final provisions (repeals) |
| 32 | Amendment to Directive 93/13/EEC | exclude | final provisions (amends Directive 93/13/EEC) |
| 33 | Amendment to Directive 1999/44/EC | exclude | final provisions (amends Directive 1999/44/EC) |
| 34 | Entry into force | exclude | final provisions (entry into force) |
| 35 | Addressees | exclude | final provisions (addressees) |

### Late Payment Directive 2011/7/EU

| article | title | decision | reason |
|---|---|---|---|
| 1 | Subject matter and scope | exclude | subject matter / scope |
| 2 | Definitions | exclude | definitions |
| 3 | Transactions between undertakings | keep | debtor undertaking must pay within the payment period or owe interest |
| 4 | Transactions between undertakings and public authorities | keep | public authority as debtor must pay within the payment period or owe interest |
| 5 | Payment schedules | exclude | parties may agree payment schedules; no duty |
| 6 | Compensation for recovery costs | keep | debtor must pay the creditor a fixed sum for recovery costs |
| 7 | Unfair contractual terms and practices | exclude | legal effect (grossly unfair terms unenforceable); duty on the Member States |
| 8 | Transparency and awareness raising | exclude | duty on the Member States and the Commission (transparency) |
| 9 | Retention of title | exclude | legal effect (retention of title); duty on the Member States |
| 10 | Recovery procedures for unchallenged claims | exclude | duty on the Member States (recovery procedures) |
| 11 | Report | exclude | reports / review |
| 12 | Transposition | exclude | transposition |
| 13 | Repeal | exclude | final provisions (repeal) |
| 14 | Entry into force | exclude | final provisions (entry into force) |
| 15 | Addressees | exclude | final provisions (addressees) |

### Sale of Goods Directive (EU) 2019/771

| article | title | decision | reason |
|---|---|---|---|
| 1 | Subject matter and purpose | exclude | subject matter / scope |
| 2 | Definitions | exclude | definitions |
| 3 | Scope | exclude | subject matter / scope |
| 4 | Level of harmonisation | exclude | subject matter / scope (level of harmonisation) |
| 5 | Conformity of goods | keep | seller must deliver goods that conform |
| 6 | Subjective requirements for conformity | keep | conformity requirements the seller's goods must meet |
| 7 | Objective requirements for conformity | keep | conformity requirements; seller must supply updates |
| 8 | Incorrect installation of the goods | keep | seller must honour remedies for incorrect installation |
| 9 | Third-party rights | keep | seller must honour remedies for third-party rights restrictions |
| 10 | Liability of the seller | keep | seller is liable for lack of conformity for two years |
| 11 | Burden of proof | exclude | burden of proof (court disputes) |
| 12 | Obligation to notify | keep | consumer must notify the seller of a lack of conformity (where the Member State provides it) |
| 13 | Remedies for lack of conformity | keep | remedies for lack of conformity the seller must honour |
| 14 | Repair or replacement of the goods | keep | seller must repair or replace free of charge and take back goods |
| 15 | Price reduction | keep | seller must honour price reduction |
| 16 | Termination of the sales contract | keep | seller must reimburse the price on termination |
| 17 | Commercial guarantees | keep | guarantor (producer or seller) is bound by the guarantee and must give a guarantee statement |
| 18 | Right of redress | exclude | right of redress of the seller; no duty |
| 19 | Enforcement | exclude | duty on the Member States (enforcement) |
| 20 | Consumer information | exclude | duty on the Member States (consumer information) |
| 21 | Mandatory nature | exclude | legal effect (mandatory nature); no action by the seller |
| 22 | Amendments to Regulation (EU) 2017/2394 and Directive 2009/22/EC | exclude | final provisions (amends other acts) |
| 23 | Repeal of Directive 1999/44/EC | exclude | final provisions (repeal) |
| 24 | Transposition | exclude | transposition |
| 25 | Review | exclude | reports / review |
| 26 | Entry into force | exclude | final provisions (entry into force) |
| 27 | Addressees | exclude | final provisions (addressees) |

### e-Commerce Directive 2000/31/EC

| article | title | decision | reason |
|---|---|---|---|
| 1 | Objective and scope | exclude | subject matter / scope |
| 2 | Definitions | exclude | definitions |
| 3 | Internal market | exclude | duty on the Member States (internal market clause) |
| 4 | Principle excluding prior authorisation | exclude | duty on the Member States (no prior authorisation) |
| 5 | General information to be provided | keep | service provider must give general information about itself |
| 6 | Information to be provided | keep | commercial communications of service providers must meet conditions |
| 7 | Unsolicited commercial communication | keep | service provider must make unsolicited e-mail identifiable and respect opt-out registers |
| 8 | Regulated professions | exclude | duty on the Member States and professional bodies (regulated professions) |
| 9 | Treatment of contracts | exclude | duty on the Member States (legal system must allow electronic contracts) |
| 10 | Information to be provided | keep | service provider must give information before the order |
| 11 | Placing of the order | keep | service provider must acknowledge the order and offer error correction |
| 12 | "Mere conduit" | exclude | liability exemption for intermediaries (mere conduit); no duty |
| 13 | "Caching" | exclude | liability exemption for intermediaries (caching); no duty |
| 14 | Hosting | exclude | liability exemption for intermediaries (hosting); no duty |
| 15 | No general obligation to monitor | exclude | duty on the Member States (no general monitoring obligation) |
| 16 | Codes of conduct | exclude | duty on the Member States and the Commission (codes of conduct) |
| 17 | Out-of-court dispute settlement | exclude | duty on the Member States (out-of-court dispute settlement) |
| 18 | Court actions | exclude | duty on the Member States (court actions) |
| 19 | Cooperation | exclude | duty on the Member States (cooperation) |
| 20 | Sanctions | exclude | penalties |
| 21 | Re-examination | exclude | reports / review |
| 22 | Transposition | exclude | transposition |
| 23 | Entry into force | exclude | final provisions (entry into force) |
| 24 | Addressees | exclude | final provisions (addressees) |

## 4. Borderline decisions (for review)

Changed by the correction of 27 Oct (exclude -> keep): GDPR 39, CRD 14, LPD 4, SGD 12.

Decisions where the rule needed interpretation, listed so they can be checked:
- Kept as rights a party must honour: GDPR 15-18, 20, 21; CRD 9, 10; SGD 8, 9, 13, 15.
- Kept although the duty depends on a Member-State option or falls on a public authority: SGD 12, LPD 4.
- Not kept because no process party gets a duty (legal effects, exceptions, court rules): CRD 12, 15, 16, 20, 27;
  LPD 5, 7, 9; SGD 11, 18; GDPR 23, 48, 79-82; ECD 12-14 (liability exemptions).
- Excluded as duties of authorities or bodies outside the process: GDPR 40-43, 45, 47.

## 5. R2 extended to the new laws (scope conditions added by code, fixed, same for all cases, never passed to the generator)

Approved 27 Oct 2026 together with the keep/exclude tables of section 3 (incl. the 27 Oct correction); written before
the corpus is built and before any code change.

The excluded scope articles (CRD 3, SGD 3, ECD 1, LPD 1, GDPR 2-3) say to whom each law applies. Since they are not in
the corpus, C3's ApplicabilityAgentV2 adds one scope IF item S1 by code to every passage of a law, chosen by the
passage id prefix (as R2 already does for the GDPR, docs/C3_V2_DEVELOPMENT.md section 9):

| prefix | scope item S1 |
|---|---|
| CRD- | the buyer is a consumer (a natural person acting for purposes which are outside that person's trade, business, craft or profession) |
| SGD- | goods are sold to a consumer (a natural person acting for purposes which are outside that person's trade, business, craft or profession) |
| ECD- | the service is an information society service (a service normally provided for remuneration, at a distance, by electronic means and at the individual request of a recipient of the service) |
| LPD- | the payment is for a commercial transaction (a transaction between undertakings or between undertakings and public authorities which leads to the delivery of goods or the provision of services for remuneration) |
| GDPR- | the process handles information about identifiable people (unchanged, R2) |

Wording aligned with the definition articles on 27 Oct 2026, before any retrieval or model run with these texts
(CRD Art. 2(1), SGD Art. 2(2) and 3(1), ECD Art. 2(a), LPD Art. 2(1); GDPR unchanged, Art. 4(1)); the first wording
and the sources are in docs/C3_V2_DEVELOPMENT.md section 9, "R3 extended to the new laws".

S1 is checked against the description like every other IF item (quote-checked by code): confirmed with a checked
quote -> scope confirmed; contradicted with a checked quote (e.g. a CRD passage and a description stating a business
buyer) -> Not applicable (R4); no checked quote -> not_stated -> at most Indeterminate. The texts are fixed in
config.yaml (c3_v2.scope_conditions), identical for every case, and never reach the generator (only requirements of
Applicable rules do). C2 gets no scope items: it receives the retrieved passages verbatim.

Definitions and subject-matter articles are not retrievable for C2 or C3: the corpus holds the kept articles only.
