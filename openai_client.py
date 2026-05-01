import os
from typing import Optional, Union
from openai import OpenAI
from openai.types.responses import Response, ResponseInputParam, ResponseStreamEvent
from openai.types import FilePurpose
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai import Stream

from config import config

class basic_chat:
    def __init__(self, 
                 base_url: str = config.OPENAI_BASE_URL, 
                 api_key: str = config.OPENAI_API_KEY, 
                 model: str = config.OPENAI_MODEL) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key
        )
        self.model_name = model

    def basic_chat(
        self,
        input: Union[str, ResponseInputParam],
        instructions: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[Response, Stream[ResponseStreamEvent]]:
        response = self.client.responses.create(
            model=self.model_name,
            instructions=instructions,
            input=input,
            stream=stream,
            **kwargs
        )
        return response

    def basic_chat_with_tools(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[ChatCompletionToolParam] = [],
        stream: bool = False,
        **kwargs
    ) -> Union[ChatCompletion, Stream[ChatCompletionChunk]]:
        """支持工具调用的聊天方法"""
        chat_params = {
            "model": self.model_name,
            "messages": messages,
            "stream": stream,
            **kwargs
        }
        if tools:
            chat_params["tools"] = tools
        response = self.client.chat.completions.create(**chat_params)
        return response

    def basic_chat_with_structured_output(
        self,
        messages: list[ChatCompletionMessageParam],
        response_format: type,
        **kwargs
    ):
        """支持结构化输出的聊天方法"""
        response = self.client.beta.chat.completions.parse(
            model=self.model_name,
            messages=messages,
            response_format=response_format,
            **kwargs
        )
        return response

    def upload_file(
        self,
        file_path: str,
        purpose: FilePurpose = "user_data",
        **kwargs
    ):
        with open(file_path, "rb") as f:
            file = self.client.files.create(
                file=f,
                purpose=purpose,
                **kwargs
            )
        return file
