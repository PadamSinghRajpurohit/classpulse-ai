"""Streamlit view for the optional teaching coach and quiz generator."""
from __future__ import annotations

from typing import Any


def render_teaching_chatbot(st: Any, chatbot: Any) -> None:
    st.markdown('<div class="page-kicker">AI TEACHING ASSISTANT</div>', unsafe_allow_html=True)
    st.title("Teaching coach & quiz builder")
    st.markdown("Plan a lesson, ask for teaching strategies, or create a student quiz from a topic.")
    st.info(
        "Gemini receives the topic/question you submit and the recent chat turns for this mode. "
        "Do not include student names, contact details, grades, recordings, or other identifying information. "
        "Answers are AI-generated; review them before using with students."
    )

    advice_tab, quiz_tab = st.tabs(["Teaching advice", "Generate a quiz"])
    for mode, tab, key, heading, placeholder in (
        ("teach", advice_tab, "teaching_chat_history", "Ask about teaching", "e.g. How can I explain fractions with a visual activity?"),
        ("quiz", quiz_tab, "quiz_chat_history", "Build a student quiz", "e.g. Create a 10-question grade 8 quiz on photosynthesis, with answers."),
    ):
        with tab:
            st.subheader(heading)
            history = st.session_state.setdefault(key, [])
            for message in history:
                with st.chat_message("user" if message["role"] == "user" else "assistant"):
                    st.markdown(message["text"])
            with st.form(f"{mode}_chat_form", clear_on_submit=True):
                prompt = st.text_area("Topic or question", placeholder=placeholder, max_chars=6000, height=100)
                submitted = st.form_submit_button("Ask Gemini" if mode == "teach" else "Generate quiz", type="primary")
            if submitted:
                if not prompt.strip():
                    st.warning("Enter a topic or question first.")
                else:
                    history.append({"role": "user", "text": prompt.strip()})
                    try:
                        answer = chatbot.respond(mode, prompt, history[:-1])
                        history.append({"role": "model", "text": answer})
                    except chatbot.ChatbotError as exc:
                        history.pop()
                        st.error(str(exc))
                    else:
                        st.rerun()
            if history and st.button("Clear conversation", key=f"clear_{mode}"):
                st.session_state[key] = []
                st.rerun()
