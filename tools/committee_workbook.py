"""Editable scenario sheets. Every formula carries a cached calculated value."""
import xlsxwriter


def workbook(data, path):
    with xlsxwriter.Workbook(path, {"strings_to_formulas": False, "strings_to_urls": False}) as book:
        head = book.add_format({"bold": True, "bg_color": "#19484C", "font_color": "white"})
        inp = book.add_format({"font_color": "#145C95", "bg_color": "#EDF5F8"})
        for kind, name, source, values, result in data["reports"]:
            index = len(book.worksheets()) + 1
            sheet = book.add_worksheet(f"{index} {kind}")
            sheet.set_column(0, 0, 38)
            sheet.set_column(1, 11, 21)
            sheet.write_row(0, 0, [name, source], head)
            sheet.freeze_panes(2, 1)
            if kind == "retention":
                sheet.write_row(1, 0, ["Когорта", "База", "Остались", "Доля"], head)
                for i, row in enumerate(result["cohorts"], 2):
                    sheet.write_row(i, 0, [row["name"], row["size"], row["retained"]], inp)
                    sheet.write_formula(i, 3, f'=IFERROR(C{i+1}/B{i+1},"")', None, row["rate"] if row["rate"] is not None else "")
                end = i + 1
                sheet.write(i+1, 0, "Взвешенная доля")
                sheet.write_formula(i+1, 3, f'=IFERROR(SUM(C3:C{end})/SUM(B3:B{end}),"")', None, result["weighted_rate"] if result["weighted_rate"] is not None else "")
            elif kind == "growth":
                sheet.write_row(1, 0, ["Начальная база",values["initial_customers"],"Цена",values["price_per_period"]], inp)
                sheet.write_row(2, 0, ["Период","Посетители","Активация","Оплата","Отток","База в конце","Выручка"], head)
                for i, (row, out) in enumerate(zip(values["periods"], result["periods"]), 4):
                    sheet.write_row(i-1, 0, [row[k] for k in ("name","eligible_visitors","activation_rate","activated_to_paid","churn_rate")], inp)
                    opening = "$B$2" if i == 4 else f"F{i-1}"
                    sheet.write_formula(i-1, 5, f"={opening}*(1-E{i})+B{i}*C{i}*D{i}", None, out["closing_customers"])
                    sheet.write_formula(i-1, 6, f"=F{i}*$D$2", None, out["closing_run_rate"])
            else:
                if kind == "economics":
                    fields = ["price","variable_cost_per_user","fixed_cost","paying_users","acquisition_spend","new_customers"]
                    formulas = [("revenue","=B3*B6"),("operating_result","=(B3-B4)*B6-B5-B7"),("acquisition_cost_per_customer",'=IFERROR(B7/B8,"")')]
                else:
                    fields = ["eligible_accounts","serviceable_share","obtainable_share","revenue_per_account_period"]
                    formulas = [("total_revenue_potential","=B3*B6"),("serviceable_revenue_potential","=B3*B4*B6"),("obtainable_revenue_scenario","=B3*B4*B5*B6")]
                sheet.write_row(1, 0, ["Показатель","Значение"], head)
                for i, key in enumerate(fields, 2):
                    sheet.write(i, 0, key)
                    sheet.write(i, 1, values[key], inp)
                for i, (key, formula) in enumerate(formulas, len(fields)+3):
                    sheet.write(i, 0, key)
                    sheet.write_formula(i, 1, formula, None, result[key] if result[key] is not None else "")
        present = {report[0] for report in data["reports"]}
        templates = {
            "economics": (["Цена", "Переменные на клиента", "Клиенты", "Постоянные", "Привлечение"], "Прибыль", "(B2-C2)*D2-E2-F2"),
            "retention": (["Размер когорты", "Остались"], "Доля", "C2/B2"),
            "growth": (["База", "Входящий поток", "Активация", "Оплата", "Отток"], "База в конце", "B2*(1-F2)+C2*D2*E2"),
            "market-size": (["Клиенты", "Доступная доля", "Доля охвата", "Доход на клиента"], "Выручка сценария", "B2*C2*D2*E2")}
        for kind, (keys, metric, expression) in templates.items():
            if kind in present:
                continue
            sheet = book.add_worksheet(kind)
            sheet.set_column(0, len(keys)+1, 22)
            sheet.write_row(0, 0, ["Сценарий", *keys, metric], head)
            sheet.write(1, 0, "Введите допущения")
            for col in range(1, len(keys)+1):
                sheet.write_blank(1,col,None,inp)
            end = chr(ord("A")+len(keys))
            sheet.write_formula(1,len(keys)+1,f'=IF(COUNT(B2:{end}2)={len(keys)},IFERROR({expression},""),"")',None,"")
        refs = book.add_worksheet("Основания")
        refs.set_column(0, 0, 16)
        refs.set_column(1, 1, 90)
        refs.set_column(2, 3, 30)
        refs.write_row(0, 0, ["ID","Утверждение","Источник","Место"], head)
        for i, row in enumerate(data["claims"], 1):
            refs.write_row(i, 0, [row[k] for k in ("id","утверждение","источник","где_в_источнике")])
