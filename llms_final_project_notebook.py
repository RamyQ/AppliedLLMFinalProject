# -*- coding: utf-8 -*-
"""LLMs Final Project Notebook

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1gJOyK7Xr2PwI4wD5OItfE6I7t82LjN5r
"""

!pip -q install transformers datasets evaluate rouge_score

from datasets import load_dataset, Dataset, DatasetDict
from transformers import AutoTokenizer, EarlyStoppingCallback

t5_base = "google-t5/t5-base"
data = load_dataset("abisee/cnn_dailymail", "3.0.0")
tokenizer = AutoTokenizer.from_pretrained(t5_base)
data

import pandas as pd
train_percent, val_percent, test_percent = 0.8, 0.1, 0.1


def load_data_sampled(max_samples=10000):
  train_df = pd.DataFrame(data['train'])
  test_df = pd.DataFrame(data['test'])
  val_df = pd.DataFrame(data['validation'])
  train_df = train_df.sample(int(max_samples * train_percent)).reset_index(drop=True)
  test_df = test_df.sample(int(max_samples * test_percent)).reset_index(drop=True)
  val_df = val_df.sample(int(max_samples * val_percent)).reset_index(drop=True)
  return train_df, test_df, val_df

train_df, test_df, val_df = load_data_sampled(max_samples=10000)

train_dataset = Dataset.from_pandas(train_df)
test_dataset = Dataset.from_pandas(test_df)
val_dataset = Dataset.from_pandas(val_df)

sampled_data = DatasetDict({
    'train': train_dataset,
    'test': test_dataset,
    'validation': val_dataset
})

print("New DatasetDict rows and features below:\n")
sampled_data

prefix = "summarize: "
def preprocess_function(examples):
    inputs = [prefix + str(article) for article in examples["article"]]
    model_inputs = tokenizer(inputs, max_length=1024, truncation=True, padding=True)

    labels = tokenizer(examples["highlights"], max_length=150, truncation=True, padding=True)

    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

tokenized_data = sampled_data.map(preprocess_function, batched=True, remove_columns=sampled_data['train'].column_names)
tokenized_data

from transformers import DataCollatorForSeq2Seq
import evaluate

data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=t5_base, label_pad_token_id=-100)
rouge_metric = evaluate.load("rouge")

import numpy as np

def compute_metrics(eval_preds):
  predictions, labels = eval_preds
  decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
  labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
  decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)

  result = rouge_metric.compute(predictions=decoded_preds, references=decoded_labels, use_stemmer=True)
  prediction_lens = [np.count_nonzero(pred != tokenizer.pad_token_id) for pred in predictions]
  result["gen_len"] = np.mean(prediction_lens)
  return {k: round(v, 4) for k, v in result.items()}

import torch
from transformers import AutoModelForSeq2SeqLM, Seq2SeqTrainingArguments, Seq2SeqTrainer

model = AutoModelForSeq2SeqLM.from_pretrained(
    t5_base,
    device_map="auto",
    torch_dtype=torch.bfloat16,
)
model.to("cuda")

model.gradient_checkpointing_enable(
    gradient_checkpointing_kwargs={"use_reentrant": False}
)
model.zero_grad()

training_arguments = Seq2SeqTrainingArguments(
    output_dir="fine-tuned-t5-cnn-dailymail-trained",
    num_train_epochs=6,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=64,
    warmup_steps=200,
    logging_steps=100,
    weight_decay=0.03,
    learning_rate = 5e-5,
    logging_dir='./logs',
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model="rouge2",
    save_total_limit=3,
    predict_with_generate=True,
    generation_max_length=150,
    generation_num_beams=5,
    bf16=True,
)

trainer = Seq2SeqTrainer(
    model=model,
    args=training_arguments,
    train_dataset=tokenized_data["train"],
    eval_dataset=tokenized_data["validation"],
    data_collator=data_collator,
    compute_metrics=compute_metrics,
    callbacks=[EarlyStoppingCallback(early_stopping_patience=2)]
)

trainer.train()

output_dir = "fine-tuned-t5-cnn-dailymail-model-trained"
trainer.save_model(output_dir)
tokenizer.save_pretrained(output_dir)



# load my now trained model
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

model_path = "fine-tuned-t5-cnn-dailymail-model"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSeq2SeqLM.from_pretrained(model_path)

!zip -r fine-tuned-t5-cnn-dailymail-model.zip fine-tuned-t5-cnn-dailymail-model

# Get a few sample articles from the test set
sample_articles = sampled_data["test"]["article"][:5]
sample_highlights = sampled_data["test"]["highlights"][:5]

# Process each article individually to avoid batch issues
for i, (article, reference) in enumerate(zip(sample_articles, sample_highlights)):
    print(f"Article {i+1}")
    print("=" * 80)

    # Prepare input for the model (single article)
    input_text = prefix + article
    inputs = tokenizer(input_text, return_tensors="pt", max_length=1024, truncation=True)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    # Generate summary
    output = model.generate(
        **inputs,
        max_length=150,
        min_length=30,
        num_beams=4,
        length_penalty=1.0,
        early_stopping=True
    )

    # Decode the generated output
    decoded_output = tokenizer.batch_decode(output, skip_special_tokens=True)[0]

    print("\nGENERATED SUMMARY:")
    # Format the generated summary with line breaks every ~80 characters
    formatted_summary = "\n".join([decoded_output[j:j+80] for j in range(0, len(decoded_output), 80)])
    print(formatted_summary)

    print("\nREFERENCE SUMMARY:")
    # Format the reference summary with line breaks every ~80 characters
    formatted_reference = "\n".join([reference[j:j+80] for j in range(0, len(reference), 80)])
    print(formatted_reference)

    print("\n" + "-" * 80 + "\n")