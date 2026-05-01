import os
from dotenv import load_dotenv

# 加载当前目录下的 .env 文件
load_dotenv()

class Config:
    """应用配置类"""

    # OpenAI配置
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "")

    # 向量化模型
    VECTOR_API_KEY: str = os.getenv("VECTOR_API_KEY", "")
    VECTOR_BASE_URL: str = os.getenv("VECTOR_BASE_URL", "")
    VECTOR_MODEL_OPENAI: str = os.getenv("VECTOR_MODEL_OPENAI_NAME", "")
    VECTOR_MODEL_CHROMADB: str = os.getenv("VECTOR_MODEL_CHROMADB_NAME", "")

    CHROMA_DB_BASE_URL: str = os.getenv("CHROMA_DB_BASE_URL", "")
    CHROMA_DB_API_KEY: str = os.getenv("CHROMA_DB_API_KEY", "")
    CHROMA_DB: str = os.getenv("CHROMA_DB", "")
    CHROMA_DB_BASE_PORT: int = int(os.getenv("CHROMA_DB_BASE_PORT", "0"))
    SEARCH_API: str = os.getenv("SEARCH_API", "")

# 创建全局配置实例
config = Config()
