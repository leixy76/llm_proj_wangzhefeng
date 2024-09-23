# -*- coding: utf-8 -*-

# ***************************************************
# * File        : LLM_LoRA.py
# * Author      : Zhefeng Wang
# * Email       : wangzhefengr@163.com
# * Date        : 2024-08-16
# * Version     : 0.1.081622
# * Description : description
# * Link        : link
# * Requirement : 相关模块版本需求(例如: numpy >= 2.1.0)
# ***************************************************

# python libraries
import os
import sys
ROOT = os.getcwd()
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import pandas as pd
import torch
from datasets import Dataset
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    DataCollatorForSeq2Seq, 
    TrainingArguments, 
    Trainer, 
    GenerationConfig
)
from peft import PeftModel, LoraConfig, TaskType, get_peft_model

# global variable
LOGGING_LABEL = __file__.split('/')[-1][:-3]

# ------------------------------
# 数据、模型、参数地址
# ------------------------------
# 微调数据地址
tuning_data_path = "D:\projects\llms_proj\llm_proj\dataset\huanhuan.json"
# 模型地址
model_path = "D:\projects\llms_proj\llm_proj\downloaded_models\LLM-Research\Meta-Llama-3.1-8B-Instruct"
# LoRA 输出对应 checkpoint 地址
lora_path = 'D:\projects\llms_proj\llm_proj\output\llama3_1_instruct_lora'

# ------------------------------
# 加载本地 LlaMA-3.1-8B-Instruct 模型
# ------------------------------
# 加载 LlaMA-3.1-8B-Instruct tokenizer
tokenizer = AutoTokenizer.from_pretrained(
    model_path, 
    use_fast = False,
    trust_remote_code = True
)
tokenizer.pad_token = tokenizer.eos_token

# 加载本地 LlaMA3.1-8B-Instruct 模型
model = AutoModelForCausalLM.from_pretrained(
    model_path,  
    torch_dtype = torch.bfloat16, 
    device_map = "auto",
    # trust_remote_code = True,
)
print(model)
model.enable_input_require_grads()  # 开启梯度检查点
print(model.dtype)
# ------------------------------
# LoRA 微调数据格式化 
# ------------------------------
def process_func(example, tokenizer):
    """
    数据格式化
    """
    # LlaMA 分词器会将一个中文字切分为多个 token，
    # 因此需要放开一些最大长度，保证数据的完整性
    MAX_LENGTH = 384
    input_ids, attention_mask, labels = [], [], []

    instruction = tokenizer(
        f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n现在你要扮演皇帝身边的女人--甄嬛<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{example['instruction'] + example['input']}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n", 
        add_special_tokens = False
    )  # add_special_tokens 不在开头加 special_tokens
    response = tokenizer(
        f"{example["output"]}<|eot_id|>", 
        add_special_tokens = False
    )

    input_ids = instruction["input_ids"] + response["input_ids"] + [tokenizer.pad_token_id]
    attention_mask = instruction["attention_mask"] + response["attention_mask"] + [1]  # 因为 eos token 咱们也是要关注的，所以补充为 1
    labels = [-100] * len(instruction["input_ids"]) + response["input_ids"] + [tokenizer.pad_token_id]

    if len(input_ids) > MAX_LENGTH:
        input_ids = input_ids[:MAX_LENGTH]
        attention_mask = attention_mask[:MAX_LENGTH]
        labels = labels[:MAX_LENGTH] 
    
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "label": labels,
    }

# 加载微调数据加载
tuning_df = pd.read_json(tuning_data_path)
tuning_ds = Dataset.from_pandas(tuning_df)
print(tuning_ds[:3])

# 数据格式化处理
tokenized_id = tuning_ds.map(process_func, remove_columns = tuning_ds.column_names)
print(tokenized_id)
print(tokenizer.decode(tokenized_id[0]["input_ids"]))
print(tokenizer.decode(filter(lambda x: x != -100, tokenized_id[1]["labels"])))
# ------------------------------
# LoRA 微调
# ------------------------------
# 定义 LoraConfig
config = LoraConfig(
    task_type = TaskType.CAUSAL_LM,
    target_modules = [
        "q_proj", "k_proj", "v_proj", 
        "o_proj", "gate_proj", 
        "up_proj", "down_proj"
    ],
    inference_mode = False,  # 训练模式
    r = 8,  # LoRA 秩
    lora_alpha = 32,  # LoRA alpha
    lora_dropout = 0.1,  # dropout 比例
)
print(config)

# 创建 Peft 模型
model = get_peft_model(model, config)
print(model.print_trainable_parameters())

# 配置 LoRA 训练参数
args = TrainingArguments(
    output_dir = lora_path,
    per_device_train_batch_size = 4,
    gradient_accumulation_steps = 4,
    logging_steps = 10,
    num_train_epochs = 3,
    save_steps = 100,  # 快速演示设置 10，建议设置为 100
    learning_rate = 1e-4,
    save_on_each_node = True,
    gradient_checkpointing = True,
)

## 使用 Trainer 训练
trainer = Trainer(
    model = model,
    args = args,
    train_dataset = tokenized_id,
    data_collator = DataCollatorForSeq2Seq(tokenizer = tokenizer, padding = True),
)
trainer.train()
# ------------------------------
# 加载 LoRA 权重推理
# ------------------------------
# 加载 LlaMA-3.1-8B-Instruct tokenizer
tokenizer = AutoTokenizer.from_pretrained(
    model_path, 
    # use_fast = True,
    trust_remote_code = True
)
# 加载本地 LlaMA3.1-8B-Instruct 模型
model = AutoModelForCausalLM.from_pretrained(
    model_path, 
    torch_dtype = torch.bfloat16,
    device_map = "auto",  
    trust_remote_code = True
).eval()

# 加载 loRA 权重
model = PeftModel.from_pretrained(
    model, 
    model_id = os.path.join(lora_path, "checkpoint-100"),
)

# 构建 prompt template
prompt = "你好呀"
messages = [
    {
        "role": "system",
        "content": "假设你是皇帝身边的女人--甄嬛。",
    },
    {
        "role": "user",
        "content": prompt,
    },
]

# 模型推理 
input_ids = tokenizer.apply_chat_template(
    messages, 
    tokenize = False
)
model_inputs = tokenizer(
    [input_ids], 
    return_tensors = "pt"
).to('cuda')
generated_ids = model.generate(
    model_inputs.input_ids, 
    max_new_tokens = 512
)
generated_ids = [
    output_ids[len(input_ids):] 
    for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
]
# 输出
response = tokenizer.batch_decode(
    generated_ids, 
    skip_special_tokens = True
)[0]
print(response)




# 测试代码 main 函数
def main():
    pass

if __name__ == "__main__":
    main()