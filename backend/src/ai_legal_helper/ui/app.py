import streamlit as st
from ai_legal_helper.observability.logging_config import setup_logging, get_logger

setup_logging("INFO")
logger = get_logger(__name__)

def main():
    st.title("AI Legal Helper (P0 Foundation)")
    st.write("This is the foundational skeleton for the AI Legal Helper project.")
    
    if st.button("Generate Test Log"):
        logger.info("Test log generated from UI")
        st.success("Log generated. Check console/file.")

if __name__ == "__main__":
    main()

