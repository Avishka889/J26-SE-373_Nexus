export interface Item {
  price: number;
  quantity: number;
}

export function total(items: Item[]): number {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}

// No test reaches this. That is on purpose: the fixture is here to prove the
// harness reports a coverage number rather than the number 100.
export function discount(amount: number, percent: number): number {
  if (percent < 0 || percent > 100) {
    throw new RangeError("a percentage is between 0 and 100");
  }
  return Math.round(amount * (1 - percent / 100) * 100) / 100;
}
