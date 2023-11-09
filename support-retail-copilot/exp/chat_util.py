from dotenv import load_dotenv, find_dotenv
import importlib, os
import yaml
import os, openai
import promptflow as pf

class ChatApp:
    context :dict = {}
    configuration :dict = None

class PromptFlowChat(ChatApp):
    def __init__(self, 
                 prompt_flow):
        messages_name, question_name, answer_name = self.find_input_output_names(prompt_flow)
        self.prompt_flow = prompt_flow
        self.question = question_name
        self.answer = answer_name
        self.chat_history = messages_name

    def find_input_output_names(self, prompt_flow):
        prompt_flow = os.path.join(prompt_flow, "flow.dag.yaml")
        messages_name, question_name, answer_name = None, None, None
        with open( prompt_flow, "r") as f:
            prompt_flow = yaml.safe_load(f)
        # find the field in the flow that has the is_chat_input: true
        for name, field in prompt_flow["inputs"].items():
            if "is_chat_input" in field and field["is_chat_input"]:
                question_name = name
                break   
        for name, field in prompt_flow["inputs"].items():
            if "is_chat_history" in field and field["is_chat_history"]:
                messages_name = name
                break   
        for name, field in prompt_flow["outputs"].items():
            if "is_chat_output" in field and field["is_chat_output"]:
                answer_name = name
                break   
        return messages_name, question_name, answer_name
        
    def __call__(self, messages, stream=False, context={}, session_state={}) -> str:
        return self.chat_completion(messages=messages, stream=stream, context=context)

    def stream_response(self, answer, result):
        response = {"object": "chat.completion.chunk", "choices": []}
        response["choices"].append({"index": 0, 
                                    "delta": {"role": "assistant", 
                                              "context": result}})
        yield response

        for token in answer:
            response = {"object": "chat.completion.chunk", "choices": []}
            response["choices"].append({"index": 0, 
                                        "delta": {"content": token}})
            yield response

    def chat_completion(self, messages, stream, context={}, session_state={}):
        adjusted_kwargs = context.copy()
        adjusted_kwargs[self.question] = messages[-1]["content"]
        pf_chat_history = self._chat_history_to_pf(messages)
        if not self.chat_history in adjusted_kwargs:
            adjusted_kwargs[self.chat_history] = pf_chat_history
        elif len(pf_chat_history) > 0:
            raise ValueError(f"chat_history in context with non-empty chat history: {pf_chat_history}")

        cli = pf.PFClient()
        result = cli.test(self.prompt_flow, inputs=adjusted_kwargs)

        if self.answer is not None:  
            answer = result.pop(self.answer)
        else:
            answer = None

        if stream:
            return self.stream_response(answer, result)
        else:
            # non-streaming response
            # but the promptflow is streaming, so we need to read out the interator
            if hasattr(answer, "__iter__") and hasattr(answer, "__next__"):
                answer_text = ""
                for token in answer:
                    answer_text += token
                answer = answer_text

            response = {"object": "chat.completion", "choices": []}
            response["choices"].append({"index": 0, 
                                        "message": {"content": answer, 
                                                    "role": "assistant", 
                                                    "context": result}})
            return response

    def _chat_history_to_openai(self, chat_history: list, question:str = None) -> list:
        """
            takes the chat history as produced by prompt flow and formats it for use in the simulator
            promptflow uses the following format:
                chat_history = [{"inputs":{"question":"What did OpenAI announce on March 2023?"},
                                 "outputs":{"answer":"On March 2023, OpenAI announced the release of GPT-4"}}]
            simulator uses the following format used by openai chat models:
                [{"role": "user", "content": "What did OpenAI announce on March 2023?"}, 
                 {"role": "assistant", "content": "On March 2023, OpenAI announced the release of GPT-4"}]
            if a question is provided, then it will be added as the last message in the chat history
            with role: user
        """
        formatted_chat_history = []
        for i in chat_history:
            formatted_chat_history.append({"role": "user", "content": i["inputs"][self.question]})
            formatted_chat_history.append({"role": "assistant", "content": i["outputs"][self.answer]})
        if question is not None:
            formatted_chat_history.append({"role": "user", "content": question})
        return formatted_chat_history
    
    def _chat_history_to_pf(self, chat_history: list) -> list:
        """
            takes the chat history as produced by openai and converts it to the prompt flow and format
            simulator uses the following format used by openai chat models:
                [{"role": "user", "content": "What did OpenAI announce on March 2023?"}, 
                 {"role": "assistant", "content": "On March 2023, OpenAI announced the release of GPT-4"}]
            promptflow uses the following format:
                chat_history = [{"inputs":{"question":"What did OpenAI announce on March 2023?"},
                                 "outputs":{"answer":"On March 2023, OpenAI announced the release of GPT-4", "context":"some context for the prior answer"}}]
        """
        chat_history = chat_history.copy()
        # filter out any messages that are not from the user or assistant
        chat_history = [message for message in chat_history if message["role"] in ["user", "assistant"]]
        pf_chat_history = []
        for i in range(0, len(chat_history)-1, 2):
            pf_chat_history.append({"inputs":{self.question: chat_history[i]["content"]},
                                    "outputs":{self.answer: chat_history[i+1]["content"]}})
        return pf_chat_history

class AzureOpenAIChat(ChatApp):
    def __init__(self,  
                 api_base=None, 
                 deployment_name=None, 
                 api_version=None,
                 api_key=None):
        
        self.start_messages :list = []
        self.api_base = self.get_env_var(api_base, "AZURE_OPENAI_API_BASE")
        self.deployment_name = self.get_env_var(deployment_name, "AZURE_OPENAI_DEPLOYMENT_NAME")
        self.api_version = self.get_env_var(api_version, "AZURE_OPENAI_API_VERSION")
        self.api_key = self.get_env_var(api_key, "AZURE_OPENAI_API_KEY")

    def get_env_var(self, env_var, default):
        if env_var is None:
            return os.environ[default]
        elif env_var.startswith("$"):
            return os.environ[env_var[1:]]
        else:
            return env_var
        

    def __call__(self, messages, stream=False, context={}, session_state={}) -> str:
        return self.chat_completion(messages=messages, stream=stream, context=context, session_state=session_state)

    def chat_completion(self, messages, stream, context, session_state):
        openai.api_base = self.api_base
        openai.api_key = self.api_key
        openai.api_version = "2023-03-15-preview" 
        openai.api_type = "azure"

        messages = self.start_messages + messages
        
        response = openai.ChatCompletion.create(
            engine=self.deployment_name,
            messages=messages,
            stream=stream,
            **context
        )

        return response

class PythonFunctionChat(ChatApp):
    def __init__(self,  
                 function_name="function_name"):
        module_name = function_name.rsplit(".", 1)[0]
        function_name = function_name.rsplit(".", 1)[1]
        print(f"loading {function_name} from module {module_name}")
        module = importlib.import_module(module_name)
        self.fn = getattr(module, function_name)

    def __call__(self, messages, stream=False, context={}) -> str:
        return self.fn(messages=messages, stream=stream, context=context)

def load_chat_app(yaml_file):
    """Load chat app from yaml file"""

    dotenv_file = find_dotenv()
    print("loading .env file: ", dotenv_file)
    _ = load_dotenv(dotenv_file)

    # load yaml file
    with open(yaml_file, "r") as f:
        chat_yaml = yaml.safe_load(f)

    if chat_yaml["type"] == "python_function":
        # load python function
        chat_app = PythonFunctionChat(function_name=chat_yaml["function_name"])
    elif chat_yaml["type"] == "promptflow":
        # load promptflow
        chat_app = PromptFlowChat(prompt_flow=chat_yaml["path"])
    elif chat_yaml["type"] == "azure_openai":
        # load openai
        chat_app = AzureOpenAIChat(api_base=chat_yaml["api_base"], 
                                   deployment_name=chat_yaml["deployment_name"], 
                                   api_version=chat_yaml["api_version"],
                                   api_key=chat_yaml["api_key"])


    if "context" in chat_yaml:
        chat_app.context = chat_yaml["context"]
    
    if "start_messages" in chat_yaml:
        chat_app.start_messages = chat_yaml["start_messages"]
    
    chat_app.configuration = chat_yaml

    return chat_app
