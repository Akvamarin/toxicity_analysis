"""
A set of functions that are used for analysis visualization of the model performance.
Moved here to avoid cluttering the notebooks with code that is not relevant for the performance analysis.
"""
import os
import pandas as pd
from matplotlib import pyplot as plt
from transformers import DistilBertForSequenceClassification, DistilBertTokenizer

from sklearn.metrics import precision_recall_curve, auc
from .constants import NON_TOXIC, TOXIC, TRUE_LABELS, PRED_LABELS, PRED_PROBS, MODEL_NAME, MODEL_MAX_LENGTH,\
     TEXT, LABEL
from copy import deepcopy
import numpy as np
from sklearn.metrics import confusion_matrix
from torch.utils.data import DataLoader
import torch
from tqdm import tqdm
from IPython.display import HTML

# ------------------------------- PREDICTION FUNCTIONS ---------------------------------------------
def predict_with_probabilities(model_path: str, tokenizer: DistilBertTokenizer,
                               df_by_language: dict[str, pd.DataFrame], device: torch.device,
                               batch_size: int = 32, conf_th: float = 0.5) -> dict[str, dict[str, list[int]]]:
    """
    Execute the prediction over the given dataframes divided by language, returning a dictionary
    containing the true and predicted labels for each language as well as the predicted probabilities

    :param model_path: str. Path to the model's directory (.pt file)
    :param tokenizer: callable. Tokenizer to use for tokenizing the data before feeding it to the model.
    :param df_by_language: dict[str, pd.DataFrame]. A dictionary containing the dataframes for each language.
    :param device: torch.device. Device to use for the model.
    :param batch_size: int. Batch size to use for the predictions.
    :param conf_th: float. Confidence threshold to use for the predictions if the probabilities are
    above it, the prediction will be toxic, otherwise it will be non-toxic.

    :return: dict[str, dict[str, list[int]]]. A dictionary with the following structure:
    {<language>: {'true_labels': list[int], 'pred_labels': list[int], 'pred_probs': list[float, float]}}

    :raises AssertionError: if the model path is not a file.
    """

    def tokenize_batch(batch):
        return tokenizer(batch, padding=True, truncation=True, max_length=MODEL_MAX_LENGTH, return_tensors="pt").to(device)

    assert os.path.isfile(model_path), f"Model path {model_path} is not a file"

    # Load the model
    model = DistilBertForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2,
                                                                ignore_mismatched_sizes=True)
    # Move the model to the device
    model = model.to(device)

    state_dict = torch.load(model_path, map_location=device)
    # Update the model's state dictionary
    model.load_state_dict(state_dict)

    # Just to make sure, put it in evaluation mode
    model.eval()

    results_by_lang = {}
    with torch.no_grad():
        for lang, lang_dataset in df_by_language.items():
            # Create a data loader for creating the batches already tokenized and in the device
            data_loader = DataLoader(lang_dataset[TEXT].tolist(), batch_size=batch_size, shuffle=False,
                                     collate_fn=tokenize_batch)
            # Create the lists for storing the predictions and probabilities
            pred_labels, pred_probs = [], []
            true_labels = lang_dataset[LABEL].tolist()

            for batch in tqdm(data_loader, desc=f"Predicting for {lang.title()}", total=len(data_loader)):
                # Execute the inference and get the logits
                logits = model(**batch).logits
                # Execute softmax to get the probabilities (detach them and cast them to numpy)
                probabilities = torch.nn.functional.softmax(logits, dim=1).detach().cpu().numpy()
                # Get the predictions by comparing the probabilities with the confidence threshold
                predictions = np.where(probabilities[:, 1] > conf_th, 1, 0)
                # Add the predictions and probabilities to the results
                pred_probs.extend(list(probabilities))
                pred_labels.extend(list(predictions))

            # Store the results for this language
            results_by_lang[lang] = {
                TRUE_LABELS: true_labels,
                PRED_LABELS: pred_labels,
                PRED_PROBS: pred_probs
            }

    return results_by_lang

# ------------------------------- VISUALIZATION FUNCTIONS ---------------------------------------------

def show_confusion_matrix(labels_and_predictions_by_lang: dict[str, dict[str, list[int]|list[float, float]]]):
    """
    Show a 2x2 plot layout each one containing the confusion matrix for a language, except for the
    last one which contains the confusion matrix for all languages combined.

    :param labels_and_predictions_by_lang: dict[str, dict[str, list[int]|list[float, float]]. A dictionary containing
    the true and predicted labels for each language. The keys of the outer dictionary are the
    languages and the keys of the inner dictionaries are the true and predicted labels (also probabilities will
    be there if generated by predict_with_probabilities but they will be ignored).

    :raises AssertionError: if the number of languages is not 4 or if the number of true and
    predicted labels is not the same.
    """

    total_labels = {
        TRUE_LABELS: [],
        PRED_LABELS: [],
    }

    for lang, labels in labels_and_predictions_by_lang.items():
        total_labels[TRUE_LABELS].extend(labels[TRUE_LABELS])
        total_labels[PRED_LABELS].extend(labels[PRED_LABELS])

    assert len(total_labels[TRUE_LABELS]) == len(total_labels[PRED_LABELS]),  \
            f"Expected true and pred labels to have the same size. " \
            f"{len(total_labels['true_labels'])} != {len(total_labels['pred_labels'])}"

    labels_and_predictions_by_lang = {**deepcopy(labels_and_predictions_by_lang),
                                      "all languages": total_labels}

    assert len(labels_and_predictions_by_lang) == 2*2, f"Expected 4 language entries, " \
                                                       f"got {list(labels_and_predictions_by_lang.values())}"
    # Make a 2x2 grid
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(13, 8))
    for i, (lang, values) in enumerate(labels_and_predictions_by_lang.items()):
        true, preds = values[TRUE_LABELS], values[PRED_LABELS]
        cm = confusion_matrix(y_true=true, y_pred=preds, normalize='true')
        # Remove the last row and cast it to percentage
        cm = cm*100
        ax = axes[i // 2, i % 2]
        ax.matshow(cm, cmap=plt.cm.Purples)
        # Calculate accuracy
        accuracy = np.mean(np.array(true) == np.array(preds)) * 100
        ax.set_title(f"{lang.title()} - Accuracy: {round(accuracy, ndigits=2)}%")
        ax.set_xlabel('True Labels')
        ax.set_ylabel('Predicted Labels')
        ax.set_xticks([0, 1], [NON_TOXIC, TOXIC])
        ax.set_yticks([0, 1], [NON_TOXIC, TOXIC])

        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                # Add the percentage to the cell
                ax.text(x=j, y=i, s=f"{round(cm[i, j], ndigits=1)}%",
                        ha='center', va='center', color='black')

    plt.tight_layout(pad=2)
    plt.show()

def plot_training_curves(train_accs: list[float], train_losses: list[float],
                         val_accs: list[float], val_losses: list[float]):
    """
    Plot the training curves for accuracy and loss comparing training and validation sets.

    :param train_accs: list[float]. Training accuracies for each epoch
    :param train_losses: list[float]. Training losses for each epoch
    :param val_accs: list[float]. Validation accuracies for each epoch
    :param val_losses: list[float]. Validation losses for each epoch

    :raises AssertionError: if training and validation accuracies or losses have different lengths
    """

    assert len(train_accs) == len(val_accs), f"Training and validation accuracies must have the same length, " \
                                                f"got {len(train_accs)} and {len(val_accs)}"
    assert len(train_losses) == len(val_losses), f"Training and validation losses must have the same length, " \
                                                    f"got {len(train_losses)} and {len(val_losses)}"
    # Create figure with two subplots: one for accuracy and one for loss
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    for ax, title, train_data, val_data in zip((ax1, ax2), ('Accuracy', 'Loss'), (train_accs, train_losses),
                                     (val_accs, val_losses)):
        # Plot the curves
        ax.plot(train_data, label=f"Training {title}")
        ax.plot(val_data, label=f"Validation {title}")
        # Set the title and labels
        ax.set_title(f'Training and Validation {title}')
        ax.set_xlabel('Epoch')
        ax.set_ylabel(title)
        ax.legend()

    # Show the plot
    plt.tight_layout()
    plt.show()

def plot_combined_precision_recall_curve(results_by_lang: dict[str, dict[str, list[int]|list[float, float]]]):
    """
    Plot the combined precision-recall curve for all languages together, and indicate the optimal threshold.

    :param results_by_lang: dict[str, dict[str, list[int]|list[float, float]]]. A dictionary containing
    the true labels, predicted labels, and predicted probabilities for each language.
    """
    total_true_labels, total_pred_probs = [], []

    # Accumulate true labels and predicted (toxic)probabilities from all languages
    for lang, data in results_by_lang.items():
        total_true_labels.extend(data[TRUE_LABELS])
        total_pred_probs.extend([toxic_prob for non_toxic_prob, toxic_prob in data[PRED_PROBS]])  # Probability of being toxic

    # Calculate precision, recall, and thresholds
    precision, recall, thresholds = precision_recall_curve(total_true_labels, total_pred_probs)
    pr_auc = auc(recall, precision)

    # Find the optimal threshold
    optimal_idx = np.argmax(np.sqrt(precision * recall))
    optimal_threshold = thresholds[optimal_idx]

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.plot(recall, precision, label=f'PR curve (area = {pr_auc:.2f})')
    plt.scatter(recall[optimal_idx], precision[optimal_idx], marker='o', color='red',
                label=f'Optimal threshold: {optimal_threshold:.2f}')
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title('Precision-Recall curve')
    plt.legend()
    plt.grid(True)
    plt.show()


def find_top_failures(dataset_by_language: dict[str, pd.DataFrame],
                      matches_by_language: dict[str, dict[str, list]],
                      top_failures: int = 5) -> dict[str, dict[str, list[dict[str, int|str|float]]]]:
    """
    Get the top 5 failures for each language and each label, sorted by confidence.
    :param dataset_by_language: dict[str, pd.DataFrame]. A dictionary containing dataframes for each language. They must
    contain a column named TEXT.
    :param matches_by_language: dict[str, dict[str, list[int]|list[float, float]]]. A dictionary containing
    the true labels, predicted labels, and predicted probabilities for each language.

    :return: dict[str, dict[str, list[dict[str, int|str|float]]]]. A dictionary with the following structure:
                {<language>: { 'False TOXIC':
                        [{'true_label': int, 'pred_label': int, 'confidence': float, 'text': str}, ...],
                            'False NON-TOXIC':
                        [{'true_label': int, 'pred_label': int, 'confidence': float, 'text': str}, ...]}}
    """
    top_failures_by_language = {}

    for lang, test_set in dataset_by_language.items():
        true_labels = matches_by_language[lang][TRUE_LABELS]
        pred_labels = matches_by_language[lang][PRED_LABELS]
        pred_probs = matches_by_language[lang][PRED_PROBS]

        failures_false_toxic, failures_false_nontoxic = [], []

        for i, (true_label, pred_label, prob) in enumerate(zip(true_labels, pred_labels, pred_probs)):
            if true_label != pred_label:
                confidence = max(prob)  # Confidence of the predicted label
                text = test_set.iloc[i][TEXT]
                failure_info = {'true_label': true_label, 'pred_label': pred_label, 'confidence': confidence, 'text': text}

                if true_label == 0:  # False TOXIC
                    failures_false_toxic.append(failure_info)
                else:  # False NON-TOXIC
                    failures_false_nontoxic.append(failure_info)

        # Sort and take top failures for each category
        top_failures_false_toxic = sorted(failures_false_toxic, key=lambda x: x['confidence'], reverse=True)[:top_failures]
        top_failures_false_nontoxic = sorted(failures_false_nontoxic, key=lambda x: x['confidence'], reverse=True)[:top_failures]

        top_failures_by_language[lang] = {f'False {TOXIC}': top_failures_false_toxic, f'False {NON_TOXIC}': top_failures_false_nontoxic}

    return top_failures_by_language

def visualize_top_failures(top_failures_by_language: dict[str, dict[str, list[dict[str, int|str|float]]]]) -> HTML:
    """
    Visualize the top failures for each language and each label, sorted by confidence.

    :param top_failures_by_language: dict[str, dict[str, list[dict[str, int|str|float]]]]. A dictionary with the following structure:
                {<language>: { 'False TOXIC':
                        [{'true_label': int, 'pred_label': int, 'confidence': float, 'text': str}, ...],
                            'False NON-TOXIC':
                        [{'true_label': int, 'pred_label': int, 'confidence': float, 'text': str}, ...]}}.
                returned by find_top_failures.

    :return: IPython.display.HTML. An HTML object containing the visualization that can be displayed in a notebook.
    """
    style = """
    <style>
    .material-card {
        box-shadow: 0 4px 8px 0 rgba(0,0,0,0.2);
        transition: 0.3s;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 20px;
        background-color: #fff;
    }

    .card-title {
        color: #06c2c2;
        font-size: 18px;
        margin-bottom: 10px;
        font-weight: bold;
    }

    .card-content {
        color: #333;
    }

    .language-section {
        margin-bottom: 30px;
    }

    .label-section {
        margin-bottom: 20px;
    }

    .section-title {
        color: #333;
        font-size: 22px;
        margin-bottom: 15px;
        font-weight: bold;
    }
    </style>
    """
    cards_html = ""

    for lang, failure_categories in top_failures_by_language.items():
        cards_html += f"<div class='language-section'><h2 class='section-title'>{lang.title()}</h2>"

        for category, failures in failure_categories.items():
            cards_html += f"<div class='label-section'><h3 class='section-title'>{category}</h3>"

            for failure in failures:
                confidence = failure['confidence']
                text = failure['text']
                true = TOXIC if failure['true_label'] == 1 else NON_TOXIC
                pred = TOXIC if failure['pred_label'] == 1 else NON_TOXIC

                cards_html += f"""
                <div class="material-card">
                    <div class="card-title">Failed with conf: {confidence:.2f}. True: {true}. Pred:{pred} </div>
                    <div class="card-content">{text}</div>
                </div>
                """

            cards_html += "</div>"  # Close label-section
        cards_html += "</div>"  # Close language-section

    # Combine the styles and HTML, then display it
    return HTML(style + cards_html)
