from dataclasses import dataclass, field
from functools import partial
from typing import Optional

from datasets import load_dataset, load_from_disk
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorWithPadding,
    HfArgumentParser,
    Trainer,
)
from transformers import TrainingArguments as _TrainingArguments


@dataclass
class ModelArguments:
    model_name_or_path: Optional[str] = field(default="baichuan-inc/Baichuan2-7B-Base")


@dataclass
class DataArguments:
    data_path: str = field(
        default=None, metadata={"help": "Path to the training data."}
    )


@dataclass
class TrainingArguments(_TrainingArguments):
    cache_dir: Optional[str] = field(default=None)
    optim: str = field(default="adamw_torch")
    model_max_length: int = field(
        default=512,
        metadata={
            "help": "Maximum sequence length. Sequences will be right padded (and possibly truncated)."
        },
    )
    use_lora: bool = field(default=False)


def dataset_transform(batch, tokenizer: AutoTokenizer = None):
    outputs = tokenizer(
        batch["prompt"],
        padding="longest",
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    labels = outputs.input_ids.clone()

    # Set the labels to -100 so that the logits are not affected by loss
    labels[outputs.attention_mask == 0] = -100

    return {
        "input_ids": outputs.input_ids,
        "attention_mask": outputs.attention_mask,
        "labels": labels,
    }


def train():
    parser = HfArgumentParser((ModelArguments, DataArguments, TrainingArguments))
    model_args, data_args, training_args = parser.parse_args_into_dataclasses()

    model = AutoModelForCausalLM.from_pretrained(
        model_args.model_name_or_path,
        trust_remote_code=True,
        cache_dir=training_args.cache_dir,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        model_args.model_name_or_path,
        use_fast=False,
        trust_remote_code=True,
        model_max_length=training_args.model_max_length,
        cache_dir=training_args.cache_dir,
    )
    tokenizer.pad_token_id = tokenizer.eos_token_id

    if training_args.use_lora:
        from peft import LoraConfig, TaskType, get_peft_model

        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            target_modules=["W_pack"],
            inference_mode=False,
            r=16,
            lora_alpha=64,
            lora_dropout=0.1,
        )
        model.enable_input_require_grads()
        model = get_peft_model(model, peft_config)
        model.print_trainable_parameters()

    try:
        dataset = load_from_disk(data_args.data_path)
        if "train" in dataset:
            dataset = dataset["train"]
    except:
        dataset = load_dataset(data_args.data_path, split="train")

    dataset.set_transform(partial(dataset_transform, tokenizer=tokenizer))
    dataset = dataset.train_test_split(test_size=1000, seed=42)

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["test"],
        tokenizer=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
    )
    trainer.train()
    trainer.save_state()
    trainer.save_model(output_dir=training_args.output_dir)


if __name__ == "__main__":
    train()
