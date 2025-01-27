#!/usr/bin/env python3

__credits__ = ['David Dale', 'Daniil Moskovskiy', 'Dmitry Ustalov']

import argparse
import sys
from functools import partial
from typing import Optional, Type, Tuple, Dict, Callable, List, Union

import numpy as np
import numpy.typing as npt
import pandas as pd
import torch
from sacrebleu import CHRF
from tqdm.auto import trange
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def prepare_target_label(model: AutoModelForSequenceClassification, target_label: Union[int, str]) -> int:
    if target_label in model.config.id2label:
        pass
    elif target_label in model.config.label2id:
        target_label = model.config.label2id.get(target_label)
    elif isinstance(target_label, str) and target_label.isnumeric() and int(target_label) in model.config.id2label:
        target_label = int(target_label)
    else:
        raise ValueError(f'target_label "{target_label}" not in model labels or ids: {model.config.id2label}.')
    assert isinstance(target_label, int)
    return target_label


def classify_texts(
        model: AutoModelForSequenceClassification,
        tokenizer: AutoTokenizer,
        texts: List[str],
        target_label: Union[int, str],
        second_texts: Optional[List[str]] = None,
        batch_size: int = 32,
        raw_logits: bool = False,
        desc: Optional[str] = None
) -> npt.NDArray[np.float64]:
    target_label = prepare_target_label(model, target_label)

    res = []

    for i in trange(0, len(texts), batch_size, desc=desc):
        inputs = [texts[i: i + batch_size]]

        if second_texts is not None:
            inputs.append(second_texts[i: i + batch_size])
        inputs = tokenizer(
            *inputs, return_tensors="pt", padding=True, truncation=True, max_length=512,
        ).to(model.device)

        with torch.no_grad():
            try:
                logits = model(**inputs).logits
                if raw_logits:
                    preds = logits[:, target_label]
                elif logits.shape[-1] > 1:
                    preds = torch.softmax(logits, -1)[:, target_label]
                else:
                    preds = torch.sigmoid(logits)[:, 0]
                preds = preds.cpu().numpy()
            except:
                print(i, i + batch_size)
                preds = [0] * len(inputs)
        res.append(preds)

    return np.concatenate(res)


def evaluate_style(
        model: AutoModelForSequenceClassification,
        tokenizer: AutoTokenizer,
        texts: List[str],
        target_label: int = 1,  # 1 is formal, 0 is informal
        batch_size: int = 32
) -> npt.NDArray[np.float64]:
    target_label = prepare_target_label(model, target_label)
    scores = classify_texts(
        model,
        tokenizer,
        texts,
        target_label,
        batch_size=batch_size,
        desc='Style'
    )
    return scores


def evaluate_meaning(
        model: AutoModelForSequenceClassification,
        tokenizer: AutoTokenizer,
        original_texts: List[str],
        rewritten_texts: List[str],
        target_label: str = "entailment",
        bidirectional: bool = True,
        batch_size: int = 32,
        aggregation: str = "prod",
) -> npt.NDArray[np.float64]:
    prepared_target_label = prepare_target_label(model, target_label)

    scores = classify_texts(
        model,
        tokenizer,
        original_texts,
        prepared_target_label,
        rewritten_texts,
        batch_size=batch_size,
        desc='Meaning'
    )
    if bidirectional:
        reverse_scores = classify_texts(
            model,
            tokenizer,
            rewritten_texts,
            prepared_target_label,
            original_texts,
            batch_size=batch_size,
            desc='Meaning'
        )
        if aggregation == "prod":
            scores = reverse_scores * scores
        elif aggregation == "mean":
            scores = (reverse_scores + scores) / 2
        elif aggregation == "f1":
            scores = 2 * reverse_scores * scores / (reverse_scores + scores)
        else:
            raise ValueError('aggregation should be one of "mean", "prod", "f1"')
    return scores


def evaluate_cola(
        model: AutoModelForSequenceClassification,
        tokenizer: AutoTokenizer,
        texts: List[str],
        target_label: int = 1,
        batch_size: int = 32
) -> npt.NDArray[np.float64]:
    target_label = prepare_target_label(model, target_label)
    scores = classify_texts(
        model,
        tokenizer,
        texts,
        target_label,
        batch_size=batch_size,
        desc='Fluency'
    )
    return scores


def evaluate_style_transfer(
        original_texts: List[str],
        rewritten_texts: List[str],
        style_model: AutoModelForSequenceClassification,
        style_tokenizer: AutoTokenizer,
        meaning_model: AutoModelForSequenceClassification,
        meaning_tokenizer: AutoTokenizer,
        fluency_model: AutoModelForSequenceClassification,
        fluency_tokenizer: AutoTokenizer,
        references: Optional[List[str]] = None,
        style_target_label: int = 1,
        meaning_target_label: str = "paraphrase",
        cola_target_label: int = 1,
        batch_size: int = 32
) -> Dict[str, npt.NDArray[np.float64]]:
    accuracy = evaluate_style(
        style_model,
        style_tokenizer,
        rewritten_texts,
        target_label=style_target_label,
        batch_size=batch_size,
    )

    similarity = evaluate_meaning(
        meaning_model,
        meaning_tokenizer,
        original_texts,
        rewritten_texts,
        batch_size=batch_size,
        bidirectional=False,
        target_label=meaning_target_label,
    )

    fluency = evaluate_cola(
        fluency_model,
        fluency_tokenizer,
        texts=rewritten_texts,
        batch_size=batch_size,
        target_label=cola_target_label,
    )

    joint = accuracy * similarity * fluency

    result = {'accuracy': accuracy, 'similarity': similarity, 'fluency': fluency, 'joint': joint}

    if references is not None:
        chrf = CHRF()

        result['chrf'] = np.array([
            chrf.sentence_score(hypothesis, [reference]).score
            for hypothesis, reference in zip(rewritten_texts, references)
        ], dtype=np.float64)

    return result


def load_model(
        model_name: Optional[str] = None,
        model: Optional[AutoModelForSequenceClassification] = None,
        tokenizer: Optional[AutoTokenizer] = None,
        model_class: Type[AutoModelForSequenceClassification] = AutoModelForSequenceClassification,
        use_cuda: bool = True
) -> Tuple[AutoModelForSequenceClassification, AutoTokenizer]:
    if model is None:
        if model_name is None:
            raise ValueError("Either model or model_name should be provided")

        model = model_class.from_pretrained(model_name)

        if torch.cuda.is_available() and use_cuda:
            model.cuda()

    if tokenizer is None:
        if model_name is None:
            raise ValueError("Either tokenizer or model_name should be provided")

        tokenizer = AutoTokenizer.from_pretrained(model_name)

    return model, tokenizer


def format_prototext(measure: str, value: str) -> str:
    return f'measure{{\n  key: "{measure}"\n  value: "{value}"\n}}\n'


def run_evaluation(
        args: argparse.Namespace,
        evaluator: Callable[..., Dict[str, npt.NDArray[np.float64]]]
) -> Dict[str, npt.NDArray[np.float64]]:
    df_input = pd.read_json(args.input, convert_dates=False, lines=True)
    df_input = df_input[['id', 'text']]
    df_input.set_index('id', inplace=True)
    df_input.rename(columns={'text': 'input'}, inplace=True)

    df_prediction = pd.read_json(args.prediction, convert_dates=False, lines=True)
    df_prediction = df_prediction[['id', 'text']]
    df_prediction.set_index('id', inplace=True)
    df_prediction.rename(columns={'text': 'prediction'}, inplace=True)

    df_references = pd.read_json(args.golden, convert_dates=False, lines=True)
    df_references = df_references[['id', 'text']]
    df_references.set_index('id', inplace=True)
    df_references.rename(columns={'text': 'reference'}, inplace=True)

    df = df_input.join(df_prediction).join(df_references)

    assert len(df) == len(df_input) == len(df_prediction) == len(df_references), \
        f'Dataset lengths {len(df_input)} & {len(df_prediction)} & {len(df_references)} != {len(df)}'

    assert not df.isna().values.any(), 'Datasets contain missing entries'

    result = evaluator(
        original_texts=df['input'].tolist(),
        rewritten_texts=df['prediction'].tolist(),
        references=df['reference'].tolist()
    )

    aggregated = {measure: np.mean(values).item() for measure, values in result.items()}

    for measure, value in aggregated.items():
        args.output.write(format_prototext(measure, str(value)))

    return result


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', '--input', type=argparse.FileType('rb'), required=True,
                        help='Initial texts before style transfer')
    parser.add_argument('-g', '--golden', type=argparse.FileType('rb'), required=True,
                        help='Ground truth texts after style transfer')
    parser.add_argument('-o', '--output', type=argparse.FileType('w', encoding='UTF-8'), default=sys.stdout,
                        help='Where to print the evaluation results')
    parser.add_argument('--style-model', type=str, required=True,
                        help='Style evaluation model on Hugging Face Hub')
    parser.add_argument('--meaning-model', type=str, required=True,
                        help='Meaning evaluation model on Hugging Face Hub')
    parser.add_argument('--fluency-model', type=str, required=True,
                        help='Fluency evaluation model on Hugging Face Hub')
    parser.add_argument('--no-cuda', action='store_true', default=False,
                        help='Disable the use of CUDA')
    parser.add_argument('prediction', type=argparse.FileType('rb'),
                        help='Your model predictions')

    args = parser.parse_args()

    style_model, style_tokenizer = load_model(args.style_model, use_cuda=not args.no_cuda)
    meaning_model, meaning_tokenizer = load_model(args.meaning_model, use_cuda=not args.no_cuda)
    fluency_model, fluency_tokenizer = load_model(args.fluency_model, use_cuda=not args.no_cuda)

    run_evaluation(args, evaluator=partial(
        evaluate_style_transfer,
        style_model=style_model,
        style_tokenizer=style_tokenizer,
        meaning_model=meaning_model,
        meaning_tokenizer=meaning_tokenizer,
        fluency_model=fluency_model,
        fluency_tokenizer=fluency_tokenizer,
        style_target_label=0,
        meaning_target_label=0,
        cola_target_label=0
    ))


if __name__ == '__main__':
    main()
