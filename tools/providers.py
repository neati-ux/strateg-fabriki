"""Bounded single-response adapters for the text operations of an approved route."""
import http.client
import json
import os
import re

DIRECT = {'anthropic', 'gemini', 'deepseek'}


def credential(provider):
    names = {'anthropic': ('ANTHROPIC_API_KEY',), 'gemini': ('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
             'deepseek': ('DEEPSEEK_API_KEY',)}
    return next((os.environ[name] for name in names[provider] if os.environ.get(name)), None)


def post(host, path, headers, payload):
    connection = http.client.HTTPSConnection(host, timeout=120)
    try:
        headers = {**headers, 'content-type': 'application/json'}
        connection.request('POST', path, json.dumps(payload).encode('utf-8'), headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise ValueError(f'{host}: HTTP {response.status}')
        body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError('Ответ API превысил 8 MiB')
        return json.loads(body)
    finally:
        connection.close()


def gemini_path(model, action):
    model = model.removeprefix('models/')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', model):
        raise ValueError('Нужен идентификатор модели Gemini Developer API')
    return f'/v1beta/models/{model}:{action}'


def input_count(provider, key, row, prompt, anthropic):
    if provider == 'anthropic':
        return anthropic('/v1/messages/count_tokens', key, {'model': row['model'],
            'messages': [{'role': 'user', 'content': prompt}]})['input_tokens']
    if provider == 'gemini':
        data = post('generativelanguage.googleapis.com', gemini_path(row['model'], 'countTokens'),
                    {'x-goog-api-key': key}, {'contents': [{'parts': [{'text': prompt}]}]})
        return data['totalTokens']
    return None


def generate(provider, key, row, prompt, anthropic):
    model, limit = row['model'], row['max_output_tokens']
    if provider == 'anthropic':
        data = anthropic('/v1/messages', key, {'model': model, 'max_tokens': limit,
                          'messages': [{'role': 'user', 'content': prompt}]})
        usage = data.get('usage') or {}
        tokens_in = usage.get('input_tokens')
        if tokens_in is not None:
            tokens_in += usage.get('cache_creation_input_tokens', 0) + usage.get('cache_read_input_tokens', 0)
        return {'text': [part['text'] for part in data['content'] if part['type'] == 'text'],
                'status': data.get('stop_reason'), 'finished': data.get('stop_reason') in ('end_turn', 'stop_sequence'),
                'input_tokens': tokens_in, 'output_tokens': usage.get('output_tokens')}
    if provider == 'gemini':
        data = post('generativelanguage.googleapis.com', gemini_path(model, 'generateContent'),
                    {'x-goog-api-key': key}, {'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'maxOutputTokens': limit, 'candidateCount': 1}})
        candidates = data.get('candidates') or [{}]
        choice, usage = candidates[0], data.get('usageMetadata') or {}
        result = [part['text'] for part in choice.get('content', {}).get('parts', []) if 'text' in part and not part.get('thought')]
        output = usage.get('candidatesTokenCount')
        if output is not None:
            output += usage.get('thoughtsTokenCount', 0)
        return {'text': result, 'status': choice.get('finishReason'), 'finished': choice.get('finishReason') == 'STOP',
                'input_tokens': usage.get('promptTokenCount'), 'output_tokens': output}
    data = post('api.deepseek.com', '/chat/completions', {'authorization': 'Bearer ' + key},
                {'model': model, 'max_tokens': limit, 'stream': False,
                 'messages': [{'role': 'user', 'content': prompt}]})
    choice, usage = (data.get('choices') or [{}])[0], data.get('usage') or {}
    text = choice.get('message', {}).get('content')
    return {'text': [text] if isinstance(text, str) and text.strip() else [],
            'status': choice.get('finish_reason'), 'finished': choice.get('finish_reason') == 'stop',
            'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens')}
