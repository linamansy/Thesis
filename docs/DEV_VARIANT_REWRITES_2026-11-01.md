# Dev variant rewrites, 1 Nov 2026

Variants 06.1, 11.1, 13.1: added text replaced by clearer versions. Target passage, expected step, author and the references are unchanged.

## 06.1

- Date: 1 Nov 2026
- Old added_text: "The shop sells kitchen items to private persons across the EU. Some customers change their mind shortly after the parcel arrives and send it back within two weeks without saying why."
- New added_text: "The shop sells kitchen items to private persons across the EU. Some customers change their mind. Within two weeks after the parcel arrives, they tell the shop by email that they withdraw from the purchase, and then send the items back."
- Reason (from the law text only, not from model outputs): The IF item "the trader is informed of the consumer's decision to withdraw" (CRD Art 13(1) with Art 11) was only implied by the old text.

## 11.1

- Date: 1 Nov 2026
- Old added_text: "The company is based in the Netherlands. When cancelling, many customers ask the company to remove their name, home address and card details from its systems."
- New added_text: "The company is based in the Netherlands. When a customer cancels the subscription, the company no longer needs the customer's name, home address and card details for the service, and many customers ask the company to remove this data from its systems."
- Reason (from the law text only, not from model outputs): None of the grounds (a)-(f) of GDPR Art 17(1) was stated in the old text.

## 13.1

- Date: 1 Nov 2026
- Old added_text: "Most complaints come from private persons whose kitchen appliance stopped working a few months after purchase. These customers usually ask for the appliance to be fixed or swapped for a new one."
- New added_text: "Most complaints come from private persons who bought a kitchen appliance from the shop, and it stopped working a few months later although they used it normally. In these cases the shop repairs the appliance or swaps it for a new one."
- Reason (from the law text only, not from model outputs): The old text did not state that the shop sold the item, that it was used normally, or that the shop repairs or replaces it (SGD Art 14(1)).

Approved by Lina on 1 Nov 2026 after reading the articles. Full check: project doc 'dev_variants_clarity_check_1nov' in the Thesis BPMN project (not in this repo).

Old frozen files (data/retrieval_study2_corpus/frozen_retrieval_v2.json, data/retrieval_study2_corpus/mediation_test_top5.json) keep the old text's queries and top-5 lists; they stay unchanged as history of the RAG v2 test. The dev baseline makes its own new freeze (data/retrieval_study2_corpus/dev/frozen_sr_dev_base1.json) from the new texts.
