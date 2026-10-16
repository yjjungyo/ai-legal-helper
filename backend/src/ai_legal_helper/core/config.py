import os

# Disable LangSmith tracing at the application level to guarantee it's not sent
os.environ["LANGCHAIN_TRACING_V2"] = "false"

