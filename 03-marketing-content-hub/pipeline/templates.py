"""
03-marketing-content-hub/pipeline/templates.py

Prompt templates for each content type the Marketing Hub generates.
Each template is tailored for its channel: tone, length, structure.
"""

from enum import Enum
from dataclasses import dataclass


class ContentType(Enum):
    LINKEDIN_POST   = "linkedin_post"
    BLOG_ARTICLE    = "blog_article"
    DEMO_SCRIPT     = "demo_script"
    EMAIL_CAMPAIGN  = "email_campaign"
    CASE_STUDY_SNIPPET = "case_study_snippet"


@dataclass
class Template:
    name: str
    description: str
    system_prompt: str
    user_template: str
    expected_length: str
    tone: str


TEMPLATES: dict[ContentType, Template] = {

    ContentType.LINKEDIN_POST: Template(
        name="LinkedIn Post",
        description="Engaging professional post optimised for LinkedIn reach",
        expected_length="150–250 words",
        tone="Conversational, insightful, mildly provocative",
        system_prompt="""You are an expert B2B content marketer writing LinkedIn posts for a data analytics company.
Your posts must:
- Open with a hook that stops scrolling (a surprising stat, counterintuitive insight, or bold question)
- Deliver ONE clear insight or lesson per post — no listicles
- Use short paragraphs (1–3 sentences max)
- End with a genuine call-to-action or thought-provoking question
- Sound like a senior practitioner speaking to peers, not a brand voice
- Never use corporate jargon: "synergy", "leverage", "holistic", "robust"
- Include 3–5 relevant hashtags at the end
- Keep total length to 150–250 words""",
        user_template="""Write a LinkedIn post about: {topic}

Use the following product/customer context to ground the post with specific facts and numbers:
{context}

The post should feel authentic, data-backed, and insight-driven.
Do NOT mention the company or product name directly unless it flows naturally.
Output only the post text — no preamble.""",
    ),

    ContentType.BLOG_ARTICLE: Template(
        name="Blog Article",
        description="SEO-optimised thought leadership article (800–1200 words)",
        expected_length="800–1200 words",
        tone="Authoritative, educational, practitioner-focused",
        system_prompt="""You are a senior content strategist writing thought leadership articles for a B2B analytics platform.
Articles must:
- Open with a compelling problem statement or industry trend
- Have clear H2 and H3 headings for scannability
- Back every claim with a specific number or example from the provided context
- Include a 'Key Takeaways' section at the end
- End with a soft CTA (e.g. 'Learn how DataFlow AI can help...')
- Be written at a post-graduate reading level — precise but not academic
- Total length: 800–1200 words""",
        user_template="""Write a blog article with the title: "{topic}"

Use the following context to add specific facts, case study outcomes, and product capabilities:
{context}

Structure:
1. Introduction (hook + problem statement)
2. Main body (3–4 H2 sections with supporting examples)
3. Key Takeaways (bullet list)
4. Conclusion with soft CTA

Output only the article in markdown format — no preamble.""",
    ),

    ContentType.DEMO_SCRIPT: Template(
        name="Demo Script",
        description="Sales demo narration script for a 15-minute product walkthrough",
        expected_length="500–800 words",
        tone="Confident, discovery-driven, outcome-focused",
        system_prompt="""You are a sales engineer writing demo scripts for a data analytics platform.
The script must:
- Start with a discovery recap ("Based on what you shared, you're trying to solve X...")
- Walk through the product naturally — connect each feature to a customer pain point
- Use the prospect's industry language and metrics
- Include natural transition phrases between sections
- End with a clear next step (trial signup, POC, follow-up meeting)
- Be structured as: Opening → Problem framing → Demo flow → ROI moment → Close
- Write dialogue in first person as if the SE is speaking
- Include [SHOW SCREEN: ...] stage directions in brackets""",
        user_template="""Write a 15-minute demo script for: {topic}

Customer context and product capabilities to highlight:
{context}

Structure the script with stage directions. The SE should sound knowledgeable but not scripted.
Output only the demo script — no preamble.""",
    ),

    ContentType.EMAIL_CAMPAIGN: Template(
        name="Email Campaign",
        description="3-email nurture sequence for a specific buyer persona",
        expected_length="3 emails × 150–200 words each",
        tone="Direct, value-first, low pressure",
        system_prompt="""You are a demand generation specialist writing email nurture sequences.
Each email must:
- Have a specific, non-generic subject line (under 50 characters)
- Open with immediate value — no 'I hope this email finds you well'
- Be scannable: short paragraphs, optional one-line emphasis
- Include ONE clear CTA per email (not multiple)
- Sequence logic: Email 1 = insight/problem, Email 2 = social proof, Email 3 = direct ask
- Tone: peer-to-peer, not vendor-to-prospect""",
        user_template="""Write a 3-email nurture sequence for: {topic}

Use the following context to personalise with specific data, case studies, and capabilities:
{context}

Format each email with:
Subject: [subject line]
Body: [email body]

Output all 3 emails in sequence — no preamble.""",
    ),

    ContentType.CASE_STUDY_SNIPPET: Template(
        name="Case Study Snippet",
        description="One-paragraph proof point for use in decks and proposals",
        expected_length="80–120 words",
        tone="Factual, specific, outcome-focused",
        system_prompt="""You write customer proof point snippets for sales decks and proposals.
Each snippet must:
- Name the customer and industry
- State the challenge in one sentence
- Describe the solution in one sentence
- Quantify the outcome with specific numbers
- Be 80–120 words — nothing more
- Sound like a business result, not a technical case study
- Never use passive voice""",
        user_template="""Write a case study snippet about: {topic}

Source material:
{context}

Output only the snippet — no heading, no preamble.""",
    ),
}
