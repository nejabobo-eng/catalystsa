def calculate_price(cost: float) -> int:
    if cost <= 0:
        raise ValueError("Invalid cost")

    if cost > 2500:
        raise ValueError("Cost exceeds R2500 limit")

    price = cost * 1.6
    return int(round(price / 10) * 10)
