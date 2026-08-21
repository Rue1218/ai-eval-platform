"""协议档多模型端点配置的输入校验测试。"""

from app.schemas import ProfileCreate, ProfileUpdate


def test_profile_create_accepts_embedding_and_reranker_configs():
    """创建请求应同时接受 Embedding 与 Reranker 的三元连接参数。"""
    profile = ProfileCreate(
        name="rag-profile",
        protocol="openai_chat",
        base_url="https://chat.example.test/v1",
        model="chat-model",
        api_key="chat-secret",
        embedding_base_url="https://embed.example.test/v1",
        embedding_model="embed-model",
        embedding_api_key="embed-secret",
        reranker_base_url="https://rerank.example.test/v1",
        reranker_model="rerank-model",
        reranker_api_key="rerank-secret",
    )

    assert str(profile.embedding_base_url).rstrip("/") == "https://embed.example.test/v1"
    assert profile.embedding_model == "embed-model"
    assert str(profile.reranker_base_url).rstrip("/") == "https://rerank.example.test/v1"
    assert profile.reranker_model == "rerank-model"


def test_profile_update_keeps_endpoint_configs_optional():
    """更新请求可以只修改主模型，不能强制要求附加模型配置。"""
    profile = ProfileUpdate(model="chat-model-v2")

    assert profile.model == "chat-model-v2"
    assert profile.embedding_model is None
    assert profile.reranker_model is None
