# -*- coding: utf-8 -*-
import os
import datetime
import evaluate
import torch
import json
from src.models.postprocess_dataset import postprocess
import numpy as np

class Trainer:
    def __init__(
        self, model, tokenizer, accelerator, optimizer, lr_scheduler, progress_bar
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.accelerator = accelerator
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler
        self.progress_bar = progress_bar
        self.metric = evaluate.load("seqeval")

    def train_epoch(self, dataloader):
        self.model.train()
        for batch in dataloader:
            outputs = self.model(**batch)
            loss = outputs.loss
            self.accelerator.backward(loss)
            self.optimizer.step()
            self.lr_scheduler.step()
            self.optimizer.zero_grad()
            self.progress_bar.update(1)

    def validate_epoch(self, dataloader):
        self.model.eval()
        for batch in dataloader:
            with torch.no_grad():
                outputs = self.model(**batch)

            predictions = outputs.logits.argmax(dim=-1)
            labels = batch["labels"]

            # Necessary to pad predictions and labels for being gathered
            predictions = self.accelerator.pad_across_processes(
                predictions, dim=1, pad_index=-100
            )
            labels = self.accelerator.pad_across_processes(
                labels, dim=1, pad_index=-100
            )

            predictions_gathered = self.accelerator.gather(predictions)
            labels_gathered = self.accelerator.gather(labels)

            true_predictions, true_labels = postprocess(
                predictions_gathered, labels_gathered
            )
            self.metric.add_batch(predictions=true_predictions, references=true_labels)

    def change_dtype(self, results: dict) -> dict:
        if isinstance(results, dict):
            for k, v in results.items():
                if isinstance(v, dict):
                    for m, n in v.items():
                        if type(n) == np.int64:
                            results[k][m] = int(n)

    def train_loop(
        self,
        train_dataloader,
        eval_dataloader,
        num_train_epochs,
        output_model_path,
        results_path,
    ):

        for epoch in range(num_train_epochs):
            self.train_epoch(train_dataloader)
            self.validate_epoch(eval_dataloader)

            results = self.metric.compute()
            print(results)
            #     # Save and upload
            self.accelerator.wait_for_everyone()
        unwrapped_model = self.accelerator.unwrap_model(self.model)
        unwrapped_model.save_pretrained(
            os.path.join(output_model_path, "last_epoch"),
            save_function=self.accelerator.save,
        )
        if self.accelerator.is_main_process:
            self.tokenizer.save_pretrained(output_model_path)
        with open(results_path, "w") as file:
            self.change_dtype(results)
            json.dump(results, file)
