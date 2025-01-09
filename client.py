import asyncio
from typing import Union

from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.contract import AsyncContract
from web3.exceptions import TransactionNotFound

from config import EXPLORERS_URL, CHAIN_ID_BY_NAME, ERC20_ABI, TOKENS_PER_CHAIN,RPC_URLS


class Client:
    def __init__(self, private_key, chain_name_code, logger = None):
        self.logger = logger
        self.private_key = private_key
        # request_kwargs = {'proxy': f'http://{proxy}'}
        rpc_url = RPC_URLS[chain_name_code]
        self.chain_name_code = chain_name_code
        self.name_native_token = 'ETH'
        self.chain_id = CHAIN_ID_BY_NAME[chain_name_code]
        # self.proxy = proxy
        self.eip_1559 = True
        self.explorer_url = EXPLORERS_URL[chain_name_code]
        self.w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        self.address = self.w3.to_checksum_address(self.w3.eth.account.from_key(self.private_key).address)

    def validate_address(self) -> bool:
        return self.w3.is_address(self.address)

    def get_contract(self, contract_address: str, abi: dict = ERC20_ABI) -> AsyncContract:
        """
        Получение контракта для abi-методов
        """
        self.logger.info(f"contract_address for get_contract() :{contract_address}")
        return self.w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contract_address),
            abi=abi
        )

    async def get_decimals(self, token_name: str) -> int:
        """
           Получение decimals заданного контракта
           """
        if token_name != self.name_native_token:
            token_contract = self.get_contract(contract_address=TOKENS_PER_CHAIN[self.chain_name_code][token_name])
            return await token_contract.functions.decimals().call()
        return 18

    def to_wei_custom(self, number: int | float, decimals: int = 18) -> int:

        unit_name = {
            6: 'mwei',
            9: 'gwei',
            18: 'ether',
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f'Can not find unit name with decimals: {decimals}')

        return self.w3.to_wei(number, unit_name)

    def from_wei_custom(self, number: int | float, decimals: int) -> Union[int, float]:

        unit_name = {
            6: 'mwei',
            9: 'gwei',
            18: 'ether',
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f'Can not find unit name with decimals: {decimals}')

        return self.w3.from_wei(number, unit_name)

    async def get_balance(self, token_name : str) -> Union[int, None]:
        """
        Получает баланс для текущего пользователя, в том числе ненативнsq токен
        """
        try:
            if token_name != self.name_native_token:
                token_contract = self.get_contract(contract_address=TOKENS_PER_CHAIN[self.chain_name_code][token_name])
                return await token_contract.functions.balanceOf(self.address).call()
            return await self.w3.eth.get_balance(self.address)
        except Exception as e:
            print(f"Ошибка при получении баланса: {e}")
            return None

    async def get_priority_fee(self) -> int:
        fee_history = await self.w3.eth.fee_history(5, 'latest', [80.0])
        non_empty_block_priority_fees = [fee[0] for fee in fee_history["reward"] if fee[0] != 0]

        divisor_priority = max(len(non_empty_block_priority_fees), 1)
        priority_fee = int(round(sum(non_empty_block_priority_fees) / divisor_priority))

        return priority_fee


    async def prepare_tx(self,  value: int | float = 0) -> dict:
        """
        Подготовка шаблона транзакций
        """
        transaction = {
            'chainId': await self.w3.eth.chain_id,
            'nonce': await self.w3.eth.get_transaction_count(self.address),
            'from': self.address,
            'value': value,
            # 'gas': 184000,
            'gasPrice': int((await self.w3.eth.gas_price) * 1.5)
        }
        # transaction['gas'] = int((await self.w3.eth.estimate_gas(transaction)) * 4)

        if self.eip_1559:
            del transaction['gasPrice']

            base_fee = await self.w3.eth.gas_price
            max_priority_fee_per_gas = await self.get_priority_fee()

            if max_priority_fee_per_gas == 0:
                max_priority_fee_per_gas = base_fee

            max_fee_per_gas = int(base_fee * 1.5 + max_priority_fee_per_gas)

            transaction['maxPriorityFeePerGas'] = max_priority_fee_per_gas
            transaction['maxFeePerGas'] = max_fee_per_gas
            transaction['type'] = '0x2'

        return transaction

    # async def get_tx_info(self, hash_tx):
    #     print(await self.w3.eth.get_transaction(hash_tx))

    async def make_approve(self, token_address: str, spender_address: str, amount_in_wei: int) -> bool:
        """
        Выполнение  транзакции аппрува для ненативного токена
        """
        approve_transaction = await (self.get_contract(contract_address=token_address).functions.approve(
            spender_address,
            amount_in_wei
        ).build_transaction(await self.prepare_tx()))

        self.logger.info(f'Make approve for {spender_address} in {token_address}')

        return await self.send_transaction(approve_transaction)

    async def send_transaction(self, transaction=None, without_gas: bool = False) -> bool:
        """
        Подписание и отправка транзакции
        """
        if not without_gas:
            transaction['gas'] = int((await self.w3.eth.estimate_gas(transaction)) * 4)

        signed_raw_tx = self.w3.eth.account.sign_transaction(transaction, self.private_key).rawTransaction
        self.logger.info('Successfully signed transaction!')

        tx_hash_bytes = await self.w3.eth.send_raw_transaction(signed_raw_tx)
        self.logger.info('Successfully sent transaction!')

        tx_hash_hex = self.w3.to_hex(tx_hash_bytes)

        return await self.wait_tx(tx_hash_hex)

    async def wait_tx(self, tx_hash) -> bool:
        """
        Ожидание результата транзакции
        """
        total_time = 0
        timeout = 120
        poll_latency = 10
        while True:
            try:
                receipts = await self.w3.eth.get_transaction_receipt(tx_hash)
                status = receipts.get("status")
                if status == 1:
                    print(f'Transaction was successful: {self.explorer_url}tx/{tx_hash}')
                    self.logger.info(f'Transaction was successful: {self.explorer_url}tx/{tx_hash}')
                    return True
                elif status is None:
                    await asyncio.sleep(poll_latency)
                else:
                    print(f'Transaction failed: {self.explorer_url}tx/{tx_hash}')
                    self.logger.error(f'Transaction failed: {self.explorer_url}tx/{tx_hash}')
                    return False
            except TransactionNotFound:
                if total_time > timeout:
                    print(f"Transaction is not in the chain after {timeout} seconds")
                    self.logger.warning(f"Transaction is not in the chain after {timeout} seconds")
                    return False
                total_time += poll_latency
                await asyncio.sleep(poll_latency)
