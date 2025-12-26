import operator

class RuleEngine:
    def __init__(self):
        self.ops = {
            ">": operator.gt,
            "<": operator.lt,
            ">=": operator.ge,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne
        }

    def _get_value(self, item, market_data):
        if item["type"] == "value":
            return item["value"]
        elif item["type"] == "indicator":
            indicator_name = item["name"]
            if indicator_name not in market_data:
                raise ValueError(f"Indicator '{indicator_name}' not found.")
            return market_data[indicator_name]
        else:
            raise ValueError(f"Unknown item type: {item['type']}")

    def evaluate(self, rule_set, market_data):
        """
        戻り値: (is_match, details)
        """
        details = {}
        all_match = True

        for condition in rule_set["conditions"]:
            code = condition["code"]
            try:
                left_val = self._get_value(condition["left"], market_data)
                right_val = self._get_value(condition["right"], market_data)
                op_func = self.ops.get(condition["operator"])

                if not op_func:
                    raise ValueError(f"Unknown operator: {condition['operator']}")

                result = op_func(left_val, right_val)
                
                # 結果を詳細に記録（UI表示用）
                details[code] = {
                    "result": bool(result),
                    "name": condition["name"],
                    "desc": condition["description"],
                    "left_val": float(left_val),
                    "right_val": float(right_val),
                    "operator": condition["operator"]
                }

                if not result:
                    all_match = False

            except Exception as e:
                all_match = False
                details[code] = {
                    "result": False,
                    "name": condition.get("name", "Unknown"),
                    "error": str(e)
                }

        return all_match, details
