from exp.chat_util import PromptFlowChat
import json 
from dotenv import load_dotenv

load_dotenv()

import concurrent.futures
import json
import os, time

from azure.ai.resources.client import AIClient
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
from azure.ai.generative.evaluate import evaluate
import tempfile, os
import promptflow as pf

def process_test(chat, line_number, test):
    messages = chat._chat_history_to_openai(chat_history=test["chat_history"], 
                                            question=test["question"])
    context = dict(customerId=test["customerId"])
    reply = chat.chat_completion(messages=messages, context=context, stream=False)
    reply_message = reply["choices"][0]["message"]
    customer_data = reply_message["context"]["customer_data"]
    reply_message["context"]["citations"].append({'id': f'customer # {customer_data["id"]}',
      'title': 'Customer information',
      'content': str(customer_data),
      'url': "don't care"})
    reply_message["context"].pop("customer_data")
    messages.append(reply_message)
    return line_number, {"messages":messages}

def batch_run(prompt_flow, tests, test_set_result_file):
    cwd = os.getcwd()
    print(f"batch run {len(tests)} tests in parallel...")
    os.chdir(prompt_flow)
    chat = PromptFlowChat(".")
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tests)) as executor:
        results = executor.map(process_test, [chat]*len(tests), range(len(tests)), tests)
    print(f"done -- {time.time() - start_time} seconds for {len(tests)} tests. {(time.time() - start_time)/len(tests)} seconds per test")

    sorted_results = sorted(results, key=lambda x: x[0])
    sorted_results = [result[1] for result in sorted_results]
    os.chdir(cwd)
    with open(test_set_result_file, "w") as f:
        for result in sorted_results:
            f.write(json.dumps(result) + "\n")
    print("saved to", test_set_result_file)
    return sorted_results


def read_eval_artifacts(result):
    tabular_result = None
    with tempfile.TemporaryDirectory() as tmpdir:
        result.download_evaluation_artifacts(tmpdir)
        import pandas as pd
        pd.set_option('display.max_colwidth', 15)
        pd.set_option('display.max_columns', None)
        tabular_result = pd.read_json(os.path.join(tmpdir, "eval_results.jsonl"), lines=True)
    return tabular_result

def evaluate_test_set(client, batch_results):
    start_time = time.time()
    print(f"batch run {len(batch_results)} evaluations...")
    result = evaluate(
            evaluation_name=f"Evaluation",
            target=None,  # chat_fn,
            data=batch_results,
            task_type="chat",
            data_mapping={
                "y_pred": "messages",
            },
            model_config={
                "api_version": os.getenv("OPENAI_API_VERSION"),
                "api_base": os.getenv("OPENAI_API_BASE"),
                "api_type": "azure",
                "api_key": os.getenv("OPENAI_API_KEY"),
                "deployment_id": os.getenv("AZURE_OPENAI_EVALUATION_DEPLOYMENT")
            },
            tracking_uri=client.tracking_uri,
        )

    print(f"done -- {time.time() - start_time} seconds for {len(batch_results)} tests. {(time.time() - start_time)/len(batch_results)} seconds per evaluation")

    return result

def evaluate_prompt_flow(prompt_flow, eval_flow, batch_results):
    start_time = time.time()

    chat_app = PromptFlowChat(prompt_flow=prompt_flow)
    results = []
    for test in batch_results:
        messages = test["messages"]
        chat_history = chat_app._chat_history_to_pf(messages[:-2])
        question = messages[-2]["content"]
        answer = messages[-1]["content"]
        # customer_data = messages[-1]["context"]["customer_data"]
        citations = messages[-1]["context"]["citations"]
        context = json.dumps({"citations": citations})
        cli = pf.PFClient()
        result = cli.test(eval_flow, inputs=dict(
            chat_history=chat_history,
            question=question,
            answer=answer,
            context=context
        ))
        print("result:", result)
        results.append(result)
    print(f"done -- {time.time() - start_time} seconds for {len(batch_results)} tests. {(time.time() - start_time)/len(batch_results)} seconds per evaluation")

    return results

if __name__ == "__main__":
    print("cwd:", os.getcwd())
    test_set_file = "data/testdata.jsonl"
    test_set_result_file = "data/replies.jsonl"
    prompt_flow = "rag_flow"
    eval_flow = "eval_flow"

    with open(test_set_file) as f:
        test_set = [json.loads(line) for line in f]
    
    batch_results = batch_run(prompt_flow, test_set, test_set_result_file)

    client = AIClient.from_config(DefaultAzureCredential())
    result = evaluate_test_set(client, batch_results)
    print(result.metrics_summary)
    # result = evaluate_prompt_flow(prompt_flow, eval_flow, batch_results)
    # import pandas as pd
    # df = pd.DataFrame(result)
    # print(df.describe())    
