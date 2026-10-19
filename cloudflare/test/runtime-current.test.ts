import { describe, expect, it } from 'vitest';
import { ApiError, bodyJson, moneyCents, now } from '../src/runtime';

describe('current shared API contracts', () => {
  it('preserves integer cents and parses Brazilian form values without float rounding', () => {
    expect(moneyCents(12345)).toBe(12345);
    expect(moneyCents('R$ 1.234,56')).toBe(123456);
    expect(moneyCents('1.005')).toBe(101);
    expect(moneyCents('0,009')).toBe(1);
    expect(moneyCents('1000000000000')).toBe(100000000000000);
    expect(moneyCents(null)).toBe(0);
    for (const bad of [true, false, -1, 'NaN', 'Infinity', '1000000000000.01', {}, []]) {
      expect(() => moneyCents(bad)).toThrow(ApiError);
    }
  });
  it('rejects invalid JSON shape/UTF8 and bounded streaming bodies', async () => {
    for (const text of ['[]', 'null', 'true', '{']) {
      await expect(bodyJson(new Request('https://radar.test', {method:'POST',body:text}))).rejects.toMatchObject({status:400});
    }
    await expect(bodyJson(new Request('https://radar.test', {method:'POST',body:new Uint8Array([255])}))).rejects.toMatchObject({status:400});
    await expect(bodyJson(new Request('https://radar.test', {method:'POST',body:'{"large":1}'}), 5)).rejects.toMatchObject({status:413});
  });
  it('uses the existing Sao Paulo wall-clock timestamp format', () => {
    expect(now()).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
  });
});
