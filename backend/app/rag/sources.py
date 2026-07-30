from pydantic import BaseModel


class KnowledgeSource(BaseModel):
    id: str
    title: str
    url: str
    license: str


KNOWLEDGE_SOURCES: list[KnowledgeSource] = [
    KnowledgeSource(
        id="nist-sp-800-61r3",
        title=(
            "NIST SP 800-61 Rev. 3 — Incident Response Recommendations and "
            "Considerations for Cybersecurity Risk Management: A CSF 2.0 Community Profile"
        ),
        url="https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-61r3.pdf",
        license="U.S. government work — public domain (17 U.S.C. 105)",
    ),
    KnowledgeSource(
        id="cisa-ir-vr-playbooks",
        title="CISA — Federal Government Cybersecurity Incident and Vulnerability Response Playbooks",
        url=(
            "https://www.cisa.gov/sites/default/files/2024-08/"
            "Federal_Government_Cybersecurity_Incident_and_Vulnerability_Response_Playbooks_508C.pdf"
        ),
        license="U.S. government work — public domain (17 U.S.C. 105), TLP:CLEAR",
    ),
]
