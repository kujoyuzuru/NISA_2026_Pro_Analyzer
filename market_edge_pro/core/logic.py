import operator

class RuleEngine:
    def __init__(self):
        self.ops = {
            ">": operator.gt, "<": operator.lt,
            ">=": operator.ge, "<=": operator.le,
            "==": operator.eq, "!=": operator.ne
        }
        # 表示用の演算子マップ
        self.op_str = {
            ">": "超え", "<": "未満",
            ">=": "以上", "<=": "以下",
            "==": "と等しい", "!=": "と異なる"
        }

    def _get_value(self, item, market_data):
        if item["type"] == "value":
            return float(item["value"]) # 必ずfloatにする
        elif item["type"] == "indicator":
            name = item["name"]
            if name not in market_data: raise ValueError(f"Missing: {name}")
            return float(market_data[name])
        raise ValueError(f"Unknown type: {item['type']}")

    def evaluate(self, rule_set, market_data):
        details = {}
        all_match = True
        
        for cond in rule_set["conditions"]:
            code = cond["code"]
            try:
                left = self._get_value(cond["left"], market_data)
                right = self._get_value(cond["right"], market_data)
                op = cond["operator"]
                
                result = self.ops[op](left, right)
                
                # 差分の計算（あとどれくらいか）
                diff = abs(left - right)
                
                details[code] = {
                    "result": bool(result),
                    "name": cond["name"],
                    "left_val": left,
                    "right_val": right,
                    "operator": op,
                    "op_str": self.op_str.get(op, op),
                    "diff": diff
                }
                if not result: all_match = False

            except Exception as e:
                all_match = False
                details[code] = { "result": False, "name": cond.get("name","Error"), "error": str(e) }

        return all_match, details
