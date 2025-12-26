import pandas as pd
import operator

class RuleEngine:
    def __init__(self):
        # 演算子のマッピング
        self.ops = {
            ">": operator.gt,
            "<": operator.lt,
            ">=": operator.ge,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne
        }

    def _get_value(self, item, market_data):
        """
        JSON内の left/right 定義から実際の値を取り出す
        item: {"type": "indicator", "name": "rsi"} or {"type": "value", "value": 40}
        market_data: 銘柄の最新指標データ (dict or Series)
        """
        if item["type"] == "value":
            return item["value"]
        
        elif item["type"] == "indicator":
            indicator_name = item["name"]
            # ここで指標名がデータにあるかチェック
            if indicator_name not in market_data:
                raise ValueError(f"Indicator '{indicator_name}' not found in market data.")
            return market_data[indicator_name]
        
        else:
            raise ValueError(f"Unknown item type: {item['type']}")

    def evaluate(self, rule_set, market_data):
        """
        特定の銘柄データに対してルールセットを評価する
        戻り値: (is_match, details)
        """
        details = {}
        all_match = True

        for condition in rule_set["conditions"]:
            code = condition["code"]
            try:
                # 左右の値を取得
                left_val = self._get_value(condition["left"], market_data)
                right_val = self._get_value(condition["right"], market_data)
                op_func = self.ops.get(condition["operator"])

                if not op_func:
                    raise ValueError(f"Unknown operator: {condition['operator']}")

                # 判定実行
                result = op_func(left_val, right_val)
                
                details[code] = {
                    "result": bool(result),
                    "desc": condition["description"],
                    "left_val": float(left_val),
                    "right_val": float(right_val)
                }

                if not result:
                    all_match = False

            except Exception as e:
                # エラー時はFalseとして扱い、理由を記録
                all_match = False
                details[code] = {
                    "result": False,
                    "error": str(e)
                }

        return all_match, details
