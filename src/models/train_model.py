# -*- coding: utf-8 -*-
import os
import fire
import mlflow
from accelerate import Accelerator
from torch.optim import AdamW
from transformers import AutoModelForTokenClassification, AutoTokenizer
from src.models.trainer import Trainer
from src.models.process_dataset import make_dataloader
from src.data.data_utils import label_names
from tqdm import tqdm
from transformers import get_scheduler
from src.config import configs
from mlflow import log_params
from dotenv import load_dotenv

load_dotenv()
remote_server_uri = os.getenv("MLFLOW_TRACKING_URI")
mlflow.set_tracking_uri(remote_server_uri)

BATCH_SIZE = configs["model"]["BATCH_SIZE"]
MODEL_CHECKPOINT = configs["model"]["MODEL_CHECKPOINT"]
LEARNING_RATE = float(configs["model"]["LEARNING_RATE"])
num_train_epochs = configs["model"]["num_train_epochs"]
num_warmup_steps = configs["model"]["num_warmup_steps"]


def train_model(input_path, output_model_path, results_path):
    with mlflow.start_run():
        log_params(configs["model"])
        mlflow.get_artifact_uri()
        print(mlflow.get_artifact_uri())
        train_dataloader = make_dataloader(
            input_path, MODEL_CHECKPOINT, BATCH_SIZE, "train"
        )
        eval_dataloader = make_dataloader(
            input_path, MODEL_CHECKPOINT, BATCH_SIZE, "validation"
        )

        print("Dataloaders loaded")

        id2label = {str(i): label for i, label in enumerate(label_names)}
        label2id = {v: k for k, v in id2label.items()}
        model = AutoModelForTokenClassification.from_pretrained(
            MODEL_CHECKPOINT,
            id2label=id2label,
            label2id=label2id,
        )
        tokenizer = AutoTokenizer.from_pretrained(MODEL_CHECKPOINT)

        print("Model loaded")
        optimizer = AdamW(model.parameters(), lr=LEARNING_RATE)
        accelerator = Accelerator()

        model, optimizer, train_dataloader, eval_dataloader = accelerator.prepare(
            model, optimizer, train_dataloader, eval_dataloader
        )

        num_update_steps_per_epoch = len(train_dataloader)
        num_training_steps = num_train_epochs * num_update_steps_per_epoch

        lr_scheduler = get_scheduler(
            "linear",
            optimizer=optimizer,
            num_warmup_steps=num_warmup_steps,
            num_training_steps=num_training_steps,
        )
        progress_bar = tqdm(range(num_training_steps))

        trainer = Trainer(
            model, tokenizer, accelerator, optimizer, lr_scheduler, progress_bar
        )
        trainer.train_loop(
            train_dataloader,
            eval_dataloader,
            num_train_epochs,
            output_model_path,
            results_path,
        )


if __name__ == "__main__":
    fire.Fire(train_model)
