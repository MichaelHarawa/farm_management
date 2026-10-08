import assert from 'node:assert/strict';
import test from 'node:test';
import { financialCurrency, moneyInput, moneyString, exactSplitTotal,
  provisionalSalePreview, validateCostShares, validatePaymentSplits } from '../src/finance/values';

test('money input freezes exact cents without a floating-point or rounding path', () => {
  assert.equal(moneyInput('1'), '1.00');
  assert.equal(moneyInput('1.1'), '1.10');
  assert.equal(moneyInput(' 0.01 '), '0.01');
  assert.equal(moneyInput('999999999999.99'), '999999999999.99');
  assert.equal(moneyInput('0', false), '0.00');
  for (const invalid of ['1.001','1.100','1e2','NaN','Infinity','-1','0','01.00','1,000.00','MWK 10','1000000000000.00']) {
    assert.throws(() => moneyInput(invalid), invalid);
  }
  assert.throws(() => moneyInput(1.1 as unknown as string));
  assert.equal(moneyString.safeParse(1.1).success, false);
  assert.equal(moneyString.safeParse('1.1').success, false);
  assert.equal(financialCurrency.safeParse('USD').success, false);
});

test('funding splits add exact cents and equal the dated payment, not another cost', () => {
  const splits = [{ fundingSourceId: 'source-A', amount: '0.10' }, { fundingSourceId: 'source-B', amount: '0.20' }];
  assert.equal(exactSplitTotal(splits), '0.30');
  assert.doesNotThrow(() => validatePaymentSplits('0.30', splits));
  assert.throws(() => validatePaymentSplits('0.31', splits));
  assert.throws(() => validatePaymentSplits('0.30', [{ fundingSourceId: '', amount: '0.30' }]));
  assert.throws(() => exactSplitTotal([{ amount: '0.001' }]));
});

test('beneficiary cost shares reconcile independently of funding origin', () => {
  assert.doesNotThrow(() => validateCostShares('100.00', [
    { batchId: 'beneficiary-A', amount: '33.33' }, { batchId: 'beneficiary-B', amount: '66.67' }]));
  assert.throws(() => validateCostShares('100.00', [{ batchId: 'beneficiary-A', amount: '99.99' }]));
  assert.throws(() => validateCostShares('100.00', [
    { batchId: 'beneficiary-A', amount: '50.00' }, { batchId: 'beneficiary-A', amount: '50.00' }]));
});

test('sale preview separates revenue, costs, cash and receivable and is only provisional', () => {
  const preview = provisionalSalePreview('3', '0.10', ['0.01','0.02'], '0.20');
  assert.deepEqual(preview, { authority: 'local-provisional', currency: 'MWK', saleTotal: '0.30',
    sellingCostTotal: '0.03', receiptAmount: '0.20', receivable: '0.10', afterSellingCosts: '0.27' });
  assert.equal(provisionalSalePreview('1', '0.10', ['0.20']).afterSellingCosts, '-0.10');
  assert.equal(provisionalSalePreview('1', '90071992547.41', []).saleTotal, '90071992547.41');
  assert.throws(() => provisionalSalePreview('1', '1.00', [], '1.01'));
  assert.throws(() => provisionalSalePreview('1.5', '1.00', []));
  assert.throws(() => provisionalSalePreview('2147483648', '1.00', []));
  assert.throws(() => provisionalSalePreview('2', '999999999999.99', []));
});
