"""Controlled multi-turn comparison using local inference in a hosted Linux runner."""
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

from llama_cpp import Llama

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["CLOUD_RESULTS"])
OUT.mkdir(exist_ok=True, parents=True)
arm = sys.argv[1]
large, small = "1.5B", "0.5B"
case = """Я отвечаю за выдачу музейных каталогов. Какую меру выбрать, что сказать посетителю и что показать директору через 14 дней?
Паспорт: основной показатель — доля уникальных заказов, полученных за 72 часа, среди всех уникальных заказов. Две площадки. Бюджет 12 000 рублей, доступен один пакет. Новые инструкции — 3 000, вечерняя смена — 15 000. Варианты можно случайно распределить внутри каждой площадки.
Тематическая подборка обращений из двух экспортов приведена ниже. Других данных о причинах нет. Напиши решение и короткий план."""
tickets = "id,тема\nR8,код истёк\nR9,закрытая дверь\nR8,код истёк\nR10,код истёк"
revision = "Новое условие от инженера: в эти 14 дней случайно разделить поток внутри площадок технически невозможно. Обнови решение и скажи, что показать директору в срок."
request = case + "\n" + tickets
engines, calls = {}, []
def call(role, size, system, turns):
    if size not in engines:
        start = time.monotonic()
        engines[size] = Llama(model_path=str(Path(os.environ["MODELS"])/f"{size}.gguf"), n_ctx=8192,
                              n_threads=2, n_batch=128, seed=71, verbose=False, chat_format="chatml")
        loads[size] = round(time.monotonic()-start,3)
    start = time.monotonic()
    result = engines[size].create_chat_completion(messages=[{"role":"system","content":system},*turns],
                                                  temperature=0, max_tokens=600)
    answer = result["choices"][0]["message"]["content"]
    calls.append(dict(role=role, model=size, seconds=round(time.monotonic()-start,3), usage=result["usage"],
                      finish=result["choices"][0]["finish_reason"], answer=answer))
    return answer
def user(text):
    return {"role":"user","content":text}
def assistant(text):
    return {"role":"assistant","content":text}
if arm not in ("chat","single","routed"):
    raise ValueError(arm)
both = "Ответь руководителю по-русски, кратко. Используй только материалы запроса."
loads = {}
start = time.monotonic()
context = [user(request)]
if arm != "chat":
    rows = list(csv.DictReader(io.StringIO(tickets)))
    unique = {row["id"]: row["тема"] for row in rows}
    computed = dict(rows=len(rows), unique=len(unique), codes=sum(v=="код истёк" for v in unique.values()))
    analyst = call("analysis", small if arm=="routed" else large, (ROOT/"agents/analyst.md").read_text(encoding="utf-8"),
                   [user(request+"\nВывод программы: "+json.dumps(computed))])
    critique = call("critique",large,(ROOT/"agents/critic.md").read_text(encoding="utf-8"),
                    [user(request+"\nПроверь аналитическую записку: "+analyst)])
    context += [user("Расчёт программы: "+json.dumps(computed)+"\nАналитик: "+analyst+"\nПроверка: "+critique)]
answer=call("recommendation",large,both,context)
updated=call("revision",large,both,[*context,assistant(answer),user(revision)])
result=dict(arm=arm, request=request,revision=revision,elapsed_seconds=round(time.monotonic()-start,3),
            load_seconds=loads,calls=calls, model_api_usd=0, runner_charge_usd=None,
            live_human_minutes=0,manager_messages="scripted",commit=os.environ.get("GITHUB_SHA"))
(OUT/f"{arm}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(arm,result["elapsed_seconds"],[(r["role"],r["usage"]) for r in calls],flush=True)
