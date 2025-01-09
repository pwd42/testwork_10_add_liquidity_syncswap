from eth_abi import abi
from client import Client
from config import SYNCSWAP_CONTRACTS, SYNCSWAP_ROUTER_ABI, SYNCSWAP_POOL_ABI, TOKENS_PER_CHAIN, ZERO_ADDRESS


class SyncSwap:
    def __init__(self, client: Client, logger = None):
        self.client = client
        self.logger = logger
        self.pool_address = "0xd3D91634Cf4C04aD1B76cE2c06F7385A897F54D3"
        self.router_contract = self.client.get_contract(
            contract_address=SYNCSWAP_CONTRACTS[self.client.chain_name_code]['router_v2'],
            abi=SYNCSWAP_ROUTER_ABI
        )

    async def add_liquidity(self, amount: int):
        inputs = [
            [ZERO_ADDRESS, amount, True]
        ]

        encode_address = abi.encode(['address'], [self.client.address])

        pool_contract = self.client.get_contract(contract_address=self.pool_address, abi=SYNCSWAP_POOL_ABI)
        total_supply = await pool_contract.functions.totalSupply().call()
        reserve_usdt, reserve_eth = await pool_contract.functions.getReserves().call()
        self.logger.info(f"total_supply - {total_supply}")
        self.logger.info(f"reserve_eth - {reserve_eth}")

        min_lp_amount_out = int(amount * total_supply / reserve_eth / 2 * 0.98)
        self.logger.info(f"inputs - {inputs}")
        self.logger.info(f"encode_address - {encode_address}")
        self.logger.info(f"min_lp_amount_out - {min_lp_amount_out}")


        transaction = await self.router_contract.functions.addLiquidity2(
            self.pool_address,
            inputs,
            encode_address,
            min_lp_amount_out,
            ZERO_ADDRESS,
            '0x',
            ZERO_ADDRESS
        ).build_transaction(await self.client.prepare_tx(value=amount))

        self.logger.info(f"transaction - {transaction}")

        return await self.client.send_transaction(transaction)

    async def burn_liquidity(self):
        tokens_config = TOKENS_PER_CHAIN[self.client.chain_name_code]
        token_address_a = tokens_config["WETH"]

        pool_contract = self.client.get_contract(contract_address=self.pool_address, abi=SYNCSWAP_POOL_ABI)
        withdraw_mode = 1
        lp_balance_in_wei = await pool_contract.functions.balanceOf(self.client.address).call()

        burn_data = abi.encode(
            ["address", "address", "uint8"],
            [token_address_a, self.client.address, withdraw_mode]
        )

        total_supply = await pool_contract.functions.totalSupply().call()
        _, reserve_eth = await pool_contract.functions.getReserves().call()

        min_eth_amount_out = int(lp_balance_in_wei * reserve_eth * 2 / total_supply * 0.98)

        await self.client.make_approve(
            self.pool_address, spender_address=self.router_contract.address, amount_in_wei=lp_balance_in_wei
        )

        transaction = await self.router_contract.functions.burnLiquiditySingle(
            self.pool_address,
            lp_balance_in_wei,
            burn_data,
            min_eth_amount_out,
            ZERO_ADDRESS,
            '0x',
        ).build_transaction(await self.client.prepare_tx())

        return await self.client.send_transaction(transaction)

